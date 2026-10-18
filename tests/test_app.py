import base64
import io

import pytest
import pymupdf
from PIL import Image

import app as app_module
from app import app
from services.page_store import PageStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    app.testing = True
    monkeypatch.setattr(
        app_module,
        "PAGE_STORE",
        PageStore(tmp_path / "state.sqlite3"),
    )
    return app.test_client()


def load_test_pages(client, monkeypatch, pages):
    monkeypatch.setattr(
        app_module.PdfService,
        "load_pdf",
        staticmethod(lambda _: pages),
    )
    return client.post(
        "/load_pdf",
        data={"pdf": (io.BytesIO(b"pdf"), "test.pdf")},
        content_type="multipart/form-data",
    )


def decode_preview(response):
    return Image.open(io.BytesIO(base64.b64decode(response.get_json()["preview"])))


def make_text_pdf():
    document = pymupdf.open()
    for text in ("edited page source", "preserved page source"):
        page = document.new_page(width=200, height=300)
        page.insert_text((40, 50), text)
    return document.tobytes()


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


def test_undo_and_redo_restore_page_edits(client, monkeypatch):
    page = Image.new("RGB", (2, 3), "white")
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200

    rotated = client.post("/rotate/0/left")
    undone = client.post("/undo/0")
    redone = client.post("/redo/0")

    assert rotated.status_code == undone.status_code == redone.status_code == 200
    assert decode_preview(rotated).size == (3, 2)
    assert decode_preview(undone).size == (2, 3)
    assert decode_preview(redone).size == (3, 2)


def test_crop_page_returns_selected_region(client, monkeypatch):
    page = Image.new("RGB", (5, 4), "white")
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200

    response = client.post(
        "/crop_page",
        json={
            "page": 0,
            "start": {"x": 1, "y": 1},
            "end": {"x": 4, "y": 3},
        },
    )

    assert response.status_code == 200
    assert decode_preview(response).size == (3, 2)


def test_clear_area_whitens_only_selected_region(client, monkeypatch):
    page = Image.new("RGB", (4, 4), (20, 30, 40))
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200

    response = client.post(
        "/clear_area",
        json={
            "page": 0,
            "start": {"x": 1, "y": 1},
            "end": {"x": 3, "y": 3},
        },
    )

    assert response.status_code == 200
    result = decode_preview(response)
    assert all(channel >= 245 for channel in result.getpixel((1, 1)))
    assert all(channel >= 245 for channel in result.getpixel((2, 2)))
    for point in ((0, 0), (3, 3)):
        assert all(
            abs(actual - expected) <= 8
            for actual, expected in zip(result.getpixel(point), (20, 30, 40))
        )


def test_selection_enhance_passes_selected_coordinates(client, monkeypatch):
    page = Image.new("RGB", (4, 4), "white")
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200
    selected = {}

    def enhance(image, start, end):
        selected.update(start=start, end=end)
        return Image.new("RGB", image.size, "blue")

    monkeypatch.setattr(app_module.ImageProcessor, "selection_enhance", enhance)
    response = client.post(
        "/selection_enhance",
        json={
            "page": 0,
            "start": {"x": 1, "y": 2},
            "end": {"x": 3, "y": 4},
        },
    )

    assert response.status_code == 200
    assert selected == {"start": {"x": 1, "y": 2}, "end": {"x": 3, "y": 4}}
    red, green, blue = decode_preview(response).getpixel((0, 0))
    assert red <= 5 and green <= 5 and blue >= 245


def test_save_pdf_preserves_unchanged_pages(client):
    source_pdf = make_text_pdf()
    loaded = client.post(
        "/load_pdf",
        data={"pdf": (io.BytesIO(source_pdf), "test.pdf")},
        content_type="multipart/form-data",
    )
    assert loaded.status_code == 200
    assert client.post("/rotate/0/left").status_code == 200

    response = client.post(
        "/save_pdf",
        json={"quality": 80, "changedPages": [0]},
    )

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    saved_pdf = pymupdf.open(stream=response.data, filetype="pdf")
    assert len(saved_pdf) == 2
    assert not saved_pdf[0].get_text().strip()
    assert "preserved page source" in saved_pdf[1].get_text()


@pytest.mark.parametrize("changed_pages", ["0", [-1], [True], None])
def test_save_pdf_rejects_invalid_changed_page_indexes(client, changed_pages):
    response = client.post(
        "/save_pdf",
        json={"changedPages": changed_pages},
    )

    assert response.status_code == 400
    assert (
        response.get_json()["error"]
        == "Changed pages must be a list of page indexes."
    )


def test_save_pdf_rejects_out_of_range_page_index(client, monkeypatch):
    page = Image.new("RGB", (2, 2), "white")
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200

    response = client.post(
        "/save_pdf",
        json={"changedPages": [1]},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "A changed page index is out of range."


def test_page_operations_return_not_found_without_loaded_document(client):
    response = client.post("/undo/0")

    assert response.status_code == 404
    assert response.get_json()["error"] == "Page does not exist."
