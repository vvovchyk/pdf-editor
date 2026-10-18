import io

import pytest
from PIL import Image

import app as app_module
from app import app

@pytest.fixture
def client():
    app.testing = True
    return app.test_client()

def test_home_page(client):
    response = client.get("/")
    assert response.status_code == 200


def test_load_pdf_returns_loaded_pages(client, monkeypatch):
    page = Image.new("RGB", (2, 2), "white")
    monkeypatch.setattr(
        app_module.PdfService,
        "load_pdf",
        staticmethod(lambda _: [page]),
    )

    response = client.post(
        "/load_pdf",
        data={"pdf": (io.BytesIO(b"pdf"), "test.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert len(response.get_json()["pages"]) == 1


