"""Build-time offline smoke test using the production Hybrid converter settings."""

import logging
import os

from docling.datamodel.base_models import InputFormat
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
    # Constructor / HTTP health alone does not load any models. Initializing the
    # PDF pipeline resolves and loads layout, table, OCR, and VLM artifacts while
    # the build has no network access.
    converter.initialize_pipeline(InputFormat.PDF)
    logger.info("event=models_loaded models=layout,tableformer,easyocr,smolvlm")
    logger.info("event=model_check_passed engine=docling-fast")


if __name__ == "__main__":
    main()
