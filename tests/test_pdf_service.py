import io

import pymupdf
import pytest
from PIL import Image

from services.pdf_service import PdfPageLimitError, PdfService
from utils.converters import pil_to_b64


def make_text_pdf():
    document = pymupdf.open()
    for text in ("edited page source", "preserved page source"):
        page = document.new_page(width=200, height=300)
        page.insert_text((40, 50), text)
    return document.tobytes()


def test_save_without_changes_returns_original_pdf():
    source_pdf = make_text_pdf()

    assert PdfService.save_pdf(source_pdf, {}, 80) == source_pdf


def test_save_replaces_only_changed_pages():
    source_pdf = make_text_pdf()
    changed_image = Image.new("RGB", (60, 40), "white")

    saved_pdf = PdfService.save_pdf(
        source_pdf,
        {"0": changed_image},
        80,
    )
    saved_document = pymupdf.open(stream=saved_pdf, filetype="pdf")

    assert len(saved_document) == 2
    assert saved_document[0].rect.width == 60
    assert saved_document[0].rect.height == 40
    assert not saved_document[0].get_text().strip()
    assert "preserved page source" in saved_document[1].get_text()


def test_load_pdf_rejects_page_count_above_limit():
    with pytest.raises(PdfPageLimitError, match="maximum allowed page count of 1"):
        PdfService.load_pdf(io.BytesIO(make_text_pdf()), max_pages=1)