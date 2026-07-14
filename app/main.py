from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import mimetypes
import re
import subprocess
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

import opendataloader_pdf
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse


OUTPUT_ROOT = Path("output")
UPLOAD_CHUNK_SIZE = 1024 * 1024

app = FastAPI(
    title="OpenDataLoader PDF Parser",
    version="1.0.0",
    description="A /file_parse compatible API backed by opendataloader-pdf.",
)


def _safe_filename(name: str | None, index: int) -> str:
    raw = Path(name or f"file_{index}.pdf").name
    cleaned = re.sub(r"[^\w.\-()\u4e00-\u9fff]", "_", raw, flags=re.UNICODE)
    return cleaned or f"file_{index}.pdf"


def _page_spec(
    start_page_id: int, end_page_id: int | None, total_pages: int | None = None
) -> str | None:
    start = max(start_page_id, 0) + 1
    if end_page_id is None:
        if start == 1:
            return None
        if total_pages is None or total_pages < start:
            return str(start)
        return str(start) if start == total_pages else f"{start}-{total_pages}"
    end = max(end_page_id, start_page_id) + 1
    return str(start) if start == end else f"{start}-{end}"


def _backend_name(backend: str) -> str:
    value = backend.strip().lower()
    if value in {"docling", "docling-fast", "hybrid"}:
        return "docling-fast"
    if value == "hancom-ai":
        return "hancom-ai"
    return "off"


def _run_opendataloader(
    input_paths: list[Path],
    parser_dir: Path,
    *,
    pages: str | None,
    backend: str,
) -> None:
    hybrid = _backend_name(backend)
    image_dir = (parser_dir / "images").resolve()
    image_dir.mkdir(parents=True, exist_ok=True)
    opendataloader_pdf.convert(
        input_path=[str(path) for path in input_paths],
        output_dir=str(parser_dir),
        format="json,markdown",
        image_output="external",
        image_dir=str(image_dir),
        pages=pages,
        hybrid=hybrid,
        hybrid_fallback=hybrid != "off",
        quiet=True,
    )


def _pdf_page_count(path: Path) -> int:
    completed = subprocess.run(
        ["pdfinfo", str(path)], capture_output=True, text=True, timeout=30
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or "pdfinfo failed")
    match = re.search(r"^Pages:\s+(\d+)\s*$", completed.stdout, flags=re.MULTILINE)
    if not match:
        raise RuntimeError(f"Cannot determine page count for {path.name}")
    return int(match.group(1))


def _pdf_page_sizes(path: Path, total_pages: int) -> dict[int, tuple[float, float]]:
    completed = subprocess.run(
        ["pdfinfo", "-f", "1", "-l", str(total_pages), "-box", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or "pdfinfo failed")

    sizes: dict[int, tuple[float, float]] = {}
    pattern = re.compile(
        r"^Page\s+(\d+)\s+size:\s+([\d.]+)\s+x\s+([\d.]+)\s+pts",
        flags=re.MULTILINE,
    )
    for page, width, height in pattern.findall(completed.stdout):
        sizes[int(page)] = (float(width), float(height))
    if len(sizes) != total_pages:
        raise RuntimeError(
            f"Cannot determine all page sizes for {path.name}: "
            f"expected {total_pages}, got {len(sizes)}"
        )
    return sizes


def _exception_message(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}"
    if not isinstance(exc, subprocess.CalledProcessError):
        return message

    details: list[str] = []
    seen: set[str] = set()
    for label, value in (("stderr", exc.stderr), ("stdout", exc.stdout)):
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        if isinstance(value, str):
            value = value.strip()
            if value and value not in seen:
                seen.add(value)
                details.append(f"{label}: {value}")
    if details:
        message = f"{message}\n" + "\n".join(details)
    return message[-8000:]


def _sanitize_unicode(value: Any) -> Any:
    """Replace lone UTF-16 surrogates that cannot be encoded as UTF-8."""
    if isinstance(value, str):
        return re.sub(r"[\ud800-\udfff]", "\ufffd", value)
    if isinstance(value, list):
        return [_sanitize_unicode(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_unicode(item) for item in value)
    if isinstance(value, dict):
        return {
            _sanitize_unicode(key): _sanitize_unicode(item)
            for key, item in value.items()
        }
    return value


def _bbox(
    element: dict[str, Any], page_sizes: dict[int, tuple[float, float]] | None = None
) -> list[int]:
    box = element.get("bounding box")
    if not isinstance(box, list) or len(box) != 4:
        return []
    try:
        left, bottom, right, top = [float(value) for value in box]
    except (TypeError, ValueError):
        return []

    if page_sizes:
        page_size = page_sizes.get(int(element.get("page number", 1) or 1))
        if page_size:
            page_width, page_height = page_size
            if page_width > 0 and page_height > 0:
                normalized = [
                    0 if left <= 0.01 else int(left * 1000 / page_width),
                    0 if top >= page_height - 0.01 else int((page_height - top) * 1000 / page_height),
                    1000 if right >= page_width - 0.01 else int(right * 1000 / page_width),
                    1000 if bottom <= 0.01 else int((page_height - bottom) * 1000 / page_height),
                ]
                return [min(max(value, 0), 1000) for value in normalized]

    values = [left, bottom, right, top]
    return [
        math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)
        for value in values
    ]


def _page_index(element: dict[str, Any]) -> int:
    page = element.get("page number", 1)
    return max(int(page or 1) - 1, 0)


def _element_text(element: dict[str, Any]) -> str:
    content = element.get("content")
    if isinstance(content, str):
        return content
    texts: list[str] = []
    for key in ("kids", "list items"):
        children = element.get(key, [])
        if isinstance(children, list):
            texts.extend(_element_text(child) for child in children if isinstance(child, dict))
    return "\n".join(text for text in texts if text)


def _table_html(element: dict[str, Any]) -> str:
    rows: list[str] = []
    for row in element.get("rows", []):
        cells: list[str] = []
        for cell in row.get("cells", []):
            text = html.escape(_element_text(cell)).replace("\n", "<br>")
            rowspan = max(int(cell.get("row span", 1) or 1), 1)
            colspan = max(int(cell.get("column span", 1) or 1), 1)
            cells.append(f'<td rowspan="{rowspan}" colspan="{colspan}">{text}</td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table>{''.join(rows)}</table>"


def _image_name(element: dict[str, Any], fallback_index: int) -> str:
    source = element.get("source")
    if isinstance(source, str) and source:
        return Path(source).name
    data = element.get("data")
    extension = "jpg" if element.get("format") == "jpeg" else "png"
    digest = hashlib.sha256(str(data or fallback_index).encode()).hexdigest()
    return f"{digest}.{extension}"


def _image_content_item(
    element: dict[str, Any],
    index: int,
    page_sizes: dict[int, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    return {
        "type": "image",
        "img_path": f"images/{_image_name(element, index)}",
        "image_caption": [],
        "image_footnote": [],
        "bbox": _bbox(element, page_sizes),
        "page_idx": _page_index(element),
    }


def _to_content_list(
    document: dict[str, Any], page_sizes: dict[int, tuple[float, float]] | None = None
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, element in enumerate(document.get("kids", [])):
        if not isinstance(element, dict):
            continue
        kind = str(element.get("type", "text"))
        common = {"bbox": _bbox(element, page_sizes), "page_idx": _page_index(element)}
        if kind == "table":
            result.append(
                {
                    "type": "table",
                    "img_path": "",
                    "table_caption": [],
                    "table_footnote": [],
                    "table_body": _table_html(element),
                    **common,
                }
            )
        elif kind == "image":
            result.append(_image_content_item(element, index, page_sizes))
        elif kind in {"header", "footer"}:
            result.append({"type": kind, "text": _element_text(element), **common})
        elif kind == "list":
            for item in element.get("list items", []):
                if isinstance(item, dict):
                    result.append(
                        {
                            "type": "text",
                            "text": _element_text(item),
                            "bbox": _bbox(item, page_sizes) or common["bbox"],
                            "page_idx": _page_index(item),
                        }
                    )
        else:
            text = _element_text(element)
            if text:
                result.append({"type": "text", "text": text, **common})

        # OpenDataLoader can nest figures inside list items, table cells, headers, etc.
        # MinerU's content_list is flat, so surface those images as standalone entries.
        for nested_index, nested in enumerate(_walk_elements(element)):
            if nested is not element and nested.get("type") == "image":
                result.append(
                    _image_content_item(nested, index * 1000 + nested_index, page_sizes)
                )
    return result


def _walk_elements(value: Any):
    if isinstance(value, dict):
        if "type" in value:
            yield value
        for child in value.values():
            yield from _walk_elements(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_elements(child)


def _image_data_uri(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/jpg" if suffix in {".jpg", ".jpeg"} else mimetypes.guess_type(path.name)[0]
    mime = mime or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _load_images(document: dict[str, Any], parser_dir: Path) -> dict[str, str]:
    images: dict[str, str] = {}
    for index, element in enumerate(_walk_elements(document)):
        if element.get("type") != "image":
            continue
        name = _image_name(element, index)
        embedded = element.get("data")
        if isinstance(embedded, str) and embedded.startswith("data:"):
            images[name] = embedded

    image_dir = (parser_dir / "images").resolve()
    if image_dir.is_dir():
        for path in sorted(image_dir.rglob("*")):
            if path.is_file():
                images[path.name] = _image_data_uri(path)
    return images


def _find_output(parser_dir: Path, stem: str, suffixes: tuple[str, ...]) -> Path | None:
    for suffix in suffixes:
        direct = parser_dir / f"{stem}{suffix}"
        if direct.is_file():
            return direct
    candidates = [p for p in parser_dir.rglob("*") if p.is_file() and p.suffix in suffixes]
    return candidates[0] if len(candidates) == 1 else None


def _parse_batch(
    inputs: list[tuple[str, Path]],
    task_dir: Path,
    *,
    start_page_id: int,
    end_page_id: int | None,
    backend: str,
    return_md: bool,
    return_content_list: bool,
    return_images: bool,
) -> list[dict[str, Any]]:
    parser_dir = task_dir / "parser"
    parser_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    page_sizes_by_path: dict[Path, dict[int, tuple[float, float]]] = {}
    try:
        page_counts: dict[Path, int] = {}
        for _, path in inputs:
            page_counts[path] = _pdf_page_count(path)
            page_sizes_by_path[path] = _pdf_page_sizes(path, page_counts[path])
        total_pages = max(page_counts.values())
        _run_opendataloader(
            [path for _, path in inputs],
            parser_dir,
            pages=_page_spec(start_page_id, end_page_id, total_pages),
            backend=backend,
        )
    except Exception as exc:
        message = _exception_message(exc)
        return [
            {
                "filename": original,
                "status": "failed",
                "error": message,
                "converted_pdf_path": str(pdf_path),
                "md_content": "",
                "content_list": "",
                "images": {},
            }
            for original, pdf_path in inputs
        ]

    for original, pdf_path in inputs:
        stem = pdf_path.stem
        json_path = _find_output(parser_dir, stem, (".json",))
        md_path = _find_output(parser_dir, stem, (".md", ".markdown"))
        try:
            if json_path is None:
                raise FileNotFoundError(f"OpenDataLoader did not create JSON for {original}")
            document = json.loads(json_path.read_text(encoding="utf-8"))
            results.append(
                {
                    "filename": original,
                    "status": "success",
                    "converted_pdf_path": str(pdf_path),
                    "md_content": (
                        md_path.read_text(encoding="utf-8") if return_md and md_path else ""
                    ),
                    "content_list": (
                        json.dumps(
                            _to_content_list(document, page_sizes_by_path[pdf_path]),
                            ensure_ascii=False,
                        )
                        if return_content_list
                        else ""
                    ),
                    "images": _load_images(document, parser_dir) if return_images else {},
                }
            )
        except Exception as exc:
            results.append(
                {
                    "filename": original,
                    "status": "failed",
                    "error": _exception_message(exc),
                    "converted_pdf_path": str(pdf_path),
                    "md_content": "",
                    "content_list": "",
                    "images": {},
                }
            )
    return results


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "parser": "opendataloader-pdf"}


@app.post("/file_parse", response_model=None)
async def file_parse(
    files: list[UploadFile] = File(...),
    parse_method: str = Form("auto"),
    formula_enable: bool = Form(True),
    table_enable: bool = Form(True),
    start_page_id: int = Form(0),
    end_page_id: int | None = Form(None),
    return_md: bool = Form(True),
    return_middle_json: bool = Form(False),
    return_model_output: bool = Form(False),
    return_content_list: bool = Form(False),
    return_images: bool = Form(False),
    return_content_middle: bool = Form(False),
    response_format_zip: bool = Form(False),
    lang: str = Form("ch"),
    lang_list: str | None = Form(None),
    output_dir: str | None = Form(None),
    backend: str = Form("pipeline"),
) -> dict[str, Any] | FileResponse:
    del parse_method, formula_enable, table_enable, return_middle_json
    del return_model_output, return_content_middle, lang, lang_list, output_dir

    started = time.perf_counter()
    task_id = uuid.uuid4().hex[:8]
    task_dir = OUTPUT_ROOT / task_id
    pdf_dir = task_dir / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    inputs: list[tuple[str, Path]] = []
    for index, upload in enumerate(files):
        original = _safe_filename(upload.filename, index)
        stored_name = original if not (pdf_dir / original).exists() else f"{index}_{original}"
        destination = pdf_dir / stored_name
        with destination.open("wb") as target:
            while chunk := await upload.read(UPLOAD_CHUNK_SIZE):
                target.write(chunk)
        await upload.close()
        inputs.append((original, destination))

    results = await run_in_threadpool(
        _parse_batch,
        inputs,
        task_dir,
        start_page_id=start_page_id,
        end_page_id=end_page_id,
        backend=backend,
        return_md=return_md,
        return_content_list=return_content_list,
        return_images=return_images,
    )
    successful = sum(item["status"] == "success" for item in results)
    payload: dict[str, Any] = {
        "code": 200,
        "message": "File parsing completed",
        "task_id": task_id,
        "time_taken": time.perf_counter() - started,
        "total_files": len(results),
        "successful": successful,
        "failed": len(results) - successful,
        "results": results,
        "output_dir": str(task_dir),
    }
    payload = _sanitize_unicode(payload)

    response_json = task_dir / "output.json"
    response_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if not response_format_zip:
        return payload

    archive = task_dir / "result.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(response_json, "output.json")
        for path in pdf_dir.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(task_dir))
    return FileResponse(archive, media_type="application/zip", filename=f"{task_id}.zip")
