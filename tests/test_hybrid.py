import io
import json
import logging
import subprocess
import urllib.error
from unittest.mock import Mock

import pytest

import app.main as parser


@pytest.mark.parametrize("end", [None, 99999])
def test_start_beyond_pdf_is_rejected(end):
    with pytest.raises(ValueError, match="exceeds PDF page count"):
        parser._page_spec(10, end, 10)


def test_health_success(monkeypatch, caplog):
    response = io.BytesIO(b'{"status":"ok"}')
    response.status = 200
    request = Mock(return_value=response)
    monkeypatch.setattr(parser.urllib.request, "urlopen", request)
    with caplog.at_level(logging.INFO):
        parser._check_hybrid_health("test-task")
    request.assert_called_once_with(f"{parser.HYBRID_URL}/health", timeout=5)
    assert "event=hybrid_healthy" in caplog.text


@pytest.mark.parametrize("body", [b'{"status":"failure"}', b'not json'])
def test_invalid_health_response(monkeypatch, body):
    response = io.BytesIO(body)
    response.status = 200
    monkeypatch.setattr(parser.urllib.request, "urlopen", Mock(return_value=response))
    with pytest.raises(RuntimeError, match="health check failed"):
        parser._check_hybrid_health("test-task")


def test_unreachable_hybrid_never_invokes_converter(monkeypatch, tmp_path, caplog):
    request = Mock(side_effect=urllib.error.URLError("Connection refused"))
    convert = Mock()
    monkeypatch.setattr(parser.urllib.request, "urlopen", request)
    monkeypatch.setattr(parser.opendataloader_pdf, "convert", convert)
    with pytest.raises(RuntimeError, match="Connection refused"):
        parser._run_opendataloader(
            [tmp_path / "a.pdf"], tmp_path / "hybrid", pages=None,
            hybrid="docling-fast", task_id="test-task",
        )
    convert.assert_not_called()
    assert "event=hybrid_unhealthy" in caplog.text
    assert "event=parse_failed engine=docling-fast" in caplog.text
    assert "HYBRID_URL" in caplog.text


def test_java_failure_is_logged_with_output(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(parser, "_check_hybrid_health", Mock())
    convert = Mock(side_effect=subprocess.CalledProcessError(
        1, ["java"], output="Backend returned HTTP 500"
    ))
    monkeypatch.setattr(parser.opendataloader_pdf, "convert", convert)
    with caplog.at_level(logging.INFO), pytest.raises(subprocess.CalledProcessError):
        parser._run_opendataloader(
            [tmp_path / "a.pdf"], tmp_path / "hybrid", pages="1-2",
            hybrid="docling-fast", task_id="test-task",
        )
    assert "Backend returned HTTP 500" in caplog.text
    assert "event=parse_finished" not in caplog.text
    assert convert.call_args.kwargs["quiet"] is False
    assert convert.call_args.kwargs["hybrid_fallback"] is False


def test_batch_clamps_each_pdf_for_both_engines(monkeypatch, tmp_path):
    inputs = [("a.pdf", tmp_path / "a.pdf"), ("b.pdf", tmp_path / "b.pdf")]
    monkeypatch.setattr(parser, "_pdf_page_count", lambda p: 2 if p.stem == "a" else 5)
    monkeypatch.setattr(parser, "_pdf_page_sizes", lambda p, n: {})
    calls = []

    def run(paths, directory, *, pages, task_id, hybrid="off"):
        calls.append((paths[0].name, pages, hybrid))
        directory.mkdir(parents=True, exist_ok=True)
        for path in paths:
            (directory / f"{path.stem}.json").write_text(json.dumps({
                "kids": [{"type": "image"}] if hybrid == "off" else []
            }))

    monkeypatch.setattr(parser, "_run_opendataloader", run)
    results = parser._parse_batch(
        inputs, tmp_path / "test-task", start_page_id=0, end_page_id=99999,
        return_md=False, return_content_list=False, return_images=False,
    )
    assert calls == [
        ("a.pdf", "1-2", "off"), ("b.pdf", "1-5", "off"),
        ("a.pdf", "1-2", "docling-fast"), ("b.pdf", "1-5", "docling-fast"),
    ]
    assert all(result["status"] == "success" for result in results)
