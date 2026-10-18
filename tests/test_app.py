import base64
import io

import pytest
import pymupdf
from PIL import Image

import app as app_module
from app import app
from services.page_store import PageStore

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


def test_document_state_is_isolated_between_clients(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "PAGE_STORE", PageStore(tmp_path / "state.sqlite3"))
    monkeypatch.setattr(
        app_module.PdfService,
        "load_pdf",
        staticmethod(lambda stream: [Image.new("RGB", (int(stream.read()), 3), "white")]),
    )
    first_client = app.test_client()
    second_client = app.test_client()

    first_load = first_client.post(
        "/load_pdf",
        data={"pdf": (io.BytesIO(b"5"), "first.pdf")},
    )
    second_load = second_client.post(
        "/load_pdf",
        data={"pdf": (io.BytesIO(b"7"), "second.pdf")},
    )

    assert first_load.status_code == second_load.status_code == 200
    assert first_client.post("/rotate/0/left").status_code == 200
    second_undo = second_client.post("/undo/0")
    second_preview = Image.open(io.BytesIO(base64.b64decode(second_undo.json["preview"])))

    assert second_undo.status_code == 200
    assert second_preview.size == (7, 3)


