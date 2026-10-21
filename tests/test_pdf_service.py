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


def make_labeled_pdf(labels):
    document = pymupdf.open()
    for label in labels:
        page = document.new_page(width=200, height=300)
        page.insert_text((40, 50), label)
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


def test_save_pdf_preserves_requested_page_order_and_omits_deleted_pages():
    source_pdf = make_labeled_pdf(["first page", "second page", "third page"])

    saved_pdf = PdfService.save_pdf(
        source_pdf,
        {},
        80,
        page_order=[2, 0],
    )
    saved_document = pymupdf.open(stream=saved_pdf, filetype="pdf")

    assert len(saved_document) == 2
    assert "third page" in saved_document[0].get_text()
    assert "first page" in saved_document[1].get_text()


def test_save_without_edits_and_default_page_order_returns_original_pdf():
    source_pdf = make_text_pdf()

    assert PdfService.save_pdf(source_pdf, {}, 80, page_order=[0, 1]) == source_pdf


def test_save_pdf_changed_images_follow_output_order_after_reordering():
    source_pdf = make_labeled_pdf(["first page", "second page"])
    changed_image = Image.new("RGB", (40, 30), "red")

    saved_pdf = PdfService.save_pdf(
        source_pdf,
        {"0": changed_image},
        80,
        page_order=[1, 0],
    )
    saved_document = pymupdf.open(stream=saved_pdf, filetype="pdf")

    assert len(saved_document) == 2
    assert not saved_document[0].get_text().strip()
    assert "first page" in saved_document[1].get_text()


def test_load_pdf_rejects_page_count_above_limit():
    with pytest.raises(PdfPageLimitError, match="maximum allowed page count of 1"):
        PdfService.load_pdf(io.BytesIO(make_text_pdf()), max_pages=1)


def test_load_pdf_rejects_page_above_pixel_limit_before_rendering(monkeypatch):
    document = pymupdf.open()
    document.new_page(width=5000, height=5000)
    monkeypatch.setattr(
        pymupdf.Page,
        "get_pixmap",
        lambda *args, **kwargs: pytest.fail("Oversized page was rendered."),
    )

    with pytest.raises(
        PdfPageLimitError,
        match="page 1 exceeds the maximum allowed size of 20000000 pixels",
    ):
        PdfService.load_pdf(io.BytesIO(document.tobytes()))


def test_load_pdf_rejects_document_above_total_pixel_limit_before_rendering(monkeypatch):
    document = pymupdf.open()
    for _ in range(6):
        document.new_page(width=4000, height=5000)
    monkeypatch.setattr(
        pymupdf.Page,
        "get_pixmap",
        lambda *args, **kwargs: pytest.fail("Oversized document was rendered."),
    )

    with pytest.raises(
        PdfPageLimitError,
        match="maximum allowed total of 100000000 pixels",
    ):
        PdfService.load_pdf(io.BytesIO(document.tobytes()))


def test_page_size_info_detects_mixed_sizes_and_most_common_format():
    document = pymupdf.open()
    document.new_page(width=200, height=300)
    document.new_page(width=200, height=300)
    document.new_page(width=100, height=150)

    info = PdfService.page_size_info(document.tobytes())

    assert info["needed"] is True
    assert info["formatCount"] == 2
    assert info["format"] == "200 × 300 pt"


def test_page_size_info_treats_rotated_pages_as_same_paper_format():
    document = pymupdf.open()
    document.new_page(width=595, height=842)
    document.new_page(width=842, height=595)

    info = PdfService.page_size_info(document.tobytes())

    assert info["needed"] is False
    assert info["format"] == "A4 (595 × 842 pt)"


def test_align_image_fits_and_centers_without_cropping():
    image = Image.new("RGB", (100, 50), "red")

    aligned = PdfService.align_image(image, 100, 100)

    assert aligned.size == (100, 100)
    assert aligned.getpixel((50, 10)) == (255, 255, 255)
    assert aligned.getpixel((50, 50)) == (255, 0, 0)


def test_align_image_preserves_landscape_orientation():
    image = Image.new("RGB", (50, 25), "blue")

    aligned = PdfService.align_image(image, 100, 200)

    assert aligned.size == (200, 100)