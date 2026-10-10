import pytest
from pdf_processor import process_pdf

def test_process_pdf_valid():
    fake_pdf = b"%PDF-1.4 fake content"
    result = process_pdf(fake_pdf)
    assert result == fake_pdf

def test_process_pdf_invalid():
    with pytest.raises(ValueError):
        process_pdf(b"")
