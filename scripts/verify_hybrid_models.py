"""Build-time offline smoke test using the production Hybrid converter settings."""

import logging
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from docling.datamodel.base_models import ConversionStatus, InputFormat
from opendataloader_pdf.hybrid_server import create_converter


def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("hybrid-model-check")
    logger.info(
        "event=model_check_start engine=docling-fast device=cpu "
        "ocr=easyocr lang=ch_sim picture_description=true artifacts=%s offline=%s",
        os.environ.get("DOCLING_ARTIFACTS_PATH"),
        os.environ.get("HF_HUB_OFFLINE"),
    )
    converter = create_converter(
        force_full_page_ocr=True,
        ocr_engine="easyocr",
        ocr_lang=["ch_sim"],
        enrich_picture_description=True,
        device="cpu",
    )
    # Constructor / HTTP health alone does not load any models.
    converter.initialize_pipeline(InputFormat.PDF)
    logger.info("event=models_loaded models=layout,tableformer,easyocr,smolvlm")

    # An image-only PDF forces OCR to run, with a simple table for layout analysis.
    with tempfile.TemporaryDirectory(prefix="hybrid-model-check-") as directory:
        pdf = Path(directory) / "scan.pdf"
        page = Image.new("RGB", (800, 600), "white")
        draw = ImageDraw.Draw(page)
        font = ImageFont.load_default(size=30)
        draw.text((50, 50), "Offline PDF model check", font=font, fill="black")
        for y in (150, 230, 310):
            draw.line((50, y, 750, y), fill="black", width=2)
        for x in (50, 400, 750):
            draw.line((x, 150, x, 310), fill="black", width=2)
        for xy, label in [((70, 170), "Item"), ((420, 170), "Count"),
                          ((70, 250), "Sample"), ((420, 250), "123")]:
            draw.text(xy, label, font=font, fill="black")
        page.save(pdf, "PDF", resolution=100)
        result = converter.convert(pdf)
        if result.status != ConversionStatus.SUCCESS:
            raise RuntimeError(f"Offline conversion failed: {result.status}: {result.errors}")
        if not result.document.export_to_markdown().strip():
            raise RuntimeError("Offline conversion returned no content")
    logger.info("event=model_check_passed engine=docling-fast")


if __name__ == "__main__":
    main()
