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
        "page_size_info",
        staticmethod(
            lambda _: {
                "needed": False,
                "format": "Test format",
                "formatCount": 1,
                "targetWidth": pages[0].width,
                "targetHeight": pages[0].height,
            }
        ),
    )
    monkeypatch.setattr(
        app_module.PdfService,
        "load_pdf",
        staticmethod(lambda _, **kwargs: pages),
    )
    return client.post(
        "/load_pdf",
        data={"pdf": (io.BytesIO(b"pdf"), "test.pdf")},
        content_type="multipart/form-data",
    )


def decode_preview(response):
    return decode_image(response.get_json()["preview"])


def decode_image(encoded_image):
    return Image.open(io.BytesIO(base64.b64decode(encoded_image)))


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
        staticmethod(lambda _, **kwargs: [page]),
    )
    monkeypatch.setattr(
        app_module.PdfService,
        "page_size_info",
        staticmethod(
            lambda _: {
                "needed": False,
                "format": "Test format",
                "formatCount": 1,
                "targetWidth": 2,
                "targetHeight": 2,
            }
        ),
    )

    response = client.post(
        "/load_pdf",
        data={"pdf": (io.BytesIO(b"pdf"), "test.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert len(response.get_json()["pages"]) == 1


def test_load_pdf_rejects_invalid_file(client):
    response = client.post(
        "/load_pdf",
        data={"pdf": (io.BytesIO(b"not a PDF"), "invalid.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "The uploaded file is not a valid PDF."


def test_load_pdf_rejects_more_than_configured_page_limit(client, monkeypatch):
    monkeypatch.setitem(app.config, "MAX_PDF_PAGES", 1)

    response = client.post(
        "/load_pdf",
        data={"pdf": (io.BytesIO(make_text_pdf()), "many-pages.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "PDF exceeds the maximum allowed page count of 1."


def test_align_pages_normalizes_all_pages_and_supports_undo(client):
    document = pymupdf.open()
    document.new_page(width=200, height=300)
    document.new_page(width=100, height=150)
    source_pdf = document.tobytes()
    loaded = client.post(
        "/load_pdf",
        data={"pdf": (io.BytesIO(source_pdf), "mixed-sizes.pdf")},
        content_type="multipart/form-data",
    )
    assert loaded.status_code == 200
    assert loaded.get_json()["alignment"]["needed"] is True
    assert loaded.get_json()["alignment"]["format"] == "200 × 300 pt"

    aligned = client.post("/align_pages")

    assert aligned.status_code == 200
    assert [
        decode_image(image).size for image in aligned.get_json()["pages"]
    ] == [(200, 300), (200, 300)]
    undone = client.post("/undo/1")
    assert decode_preview(undone).size == (100, 150)


def test_align_pages_rejects_uniform_size_document(client):
    document = pymupdf.open()
    document.new_page(width=200, height=300)
    source_pdf = document.tobytes()
    loaded = client.post(
        "/load_pdf",
        data={"pdf": (io.BytesIO(source_pdf), "same-sizes.pdf")},
        content_type="multipart/form-data",
    )
    assert loaded.status_code == 200
    assert loaded.get_json()["alignment"]["needed"] is False

    response = client.post("/align_pages")

    assert response.status_code == 400
    assert response.get_json()["error"] == "All pages already use the same paper size."


def test_document_state_is_isolated_between_clients(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "PAGE_STORE", PageStore(tmp_path / "state.sqlite3"))
    monkeypatch.setattr(
        app_module.PdfService,
        "load_pdf",
        staticmethod(
            lambda stream, **kwargs: [
                Image.new("RGB", (int(stream.read()), 3), "white")
            ]
        ),
    )
    monkeypatch.setattr(
        app_module.PdfService,
        "page_size_info",
        staticmethod(
            lambda _: {
                "needed": False,
                "format": "Test format",
                "formatCount": 1,
                "targetWidth": 1,
                "targetHeight": 3,
            }
        ),
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


@pytest.mark.parametrize(
    ("mode", "value"),
    [
        ("not-a-mode", "1"),
        ("contrast", "not-a-number"),
        ("contrast", "nan"),
        ("contrast", "inf"),
        ("contrast", "2.6"),
        ("brightness", "0.4"),
        ("sharpness", "3.1"),
        ("denoise", "6"),
    ],
)
def test_enhance_rejects_invalid_mode_or_value(client, monkeypatch, mode, value):
    page = Image.new("RGB", (2, 2), "white")
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200

    response = client.post(f"/enhance/0/{mode}/{value}")

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_rotate_rejects_invalid_direction(client, monkeypatch):
    page = Image.new("RGB", (2, 2), "white")
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200

    response = client.post("/rotate/0/up")

    assert response.status_code == 400
    assert response.get_json()["error"] == "Rotation direction must be 'left' or 'right'."


@pytest.mark.parametrize(
    "selection",
    [
        {"page": 0, "start": {"x": -1, "y": 0}, "end": {"x": 2, "y": 2}},
        {"page": 0, "start": {"x": 0, "y": 0}, "end": {"x": 3, "y": 2}},
        {"page": 0, "start": {"x": 1.5, "y": 0}, "end": {"x": 2, "y": 2}},
        {"page": 0, "start": {"x": 0, "y": 0}, "end": {"x": 0, "y": 2}},
    ],
)
def test_clear_area_rejects_invalid_selection(client, monkeypatch, selection):
    page = Image.new("RGB", (2, 2), "white")
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200

    response = client.post("/clear_area", json=selection)

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_crop_rejects_non_json_request(client):
    response = client.post("/crop_page", data="not JSON")

    assert response.status_code == 400
    assert response.get_json()["error"] == "A JSON object is required."


def test_save_pdf_rejects_non_numeric_quality(client):
    response = client.post("/save_pdf", json={"quality": "high"})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Quality must be a finite number."


def test_oversized_upload_returns_json_error(client, monkeypatch):
    monkeypatch.setitem(app.config, "MAX_CONTENT_LENGTH", 100)

    response = client.post(
        "/load_pdf",
        data={"pdf": (io.BytesIO(b"x" * 200), "large.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 413
    assert response.get_json()["error"] == "The request exceeds the maximum allowed size."
