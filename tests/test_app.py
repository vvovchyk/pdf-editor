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


def make_labeled_pdf(labels):
    document = pymupdf.open()
    for label in labels:
        page = document.new_page(width=200, height=300)
        page.insert_text((40, 50), label)
    return document.tobytes()


def configure_payments(monkeypatch):
    monkeypatch.setitem(app.config, "PAYMENTS_ENABLED", True)
    monkeypatch.setitem(app.config, "STRIPE_SECRET_KEY", "sk_test_configured")
    monkeypatch.setitem(app.config, "STRIPE_WEBHOOK_SECRET", "whsec_configured")
    monkeypatch.setitem(
        app.config,
        "PUBLIC_BASE_URL",
        "https://sackofhacks.com/pdf-cleaner",
    )


def test_home_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Editing a page rasterizes it" in response.data
    assert b"ca-pub-2211245923059324" in response.data
    assert b'data-ad-slot="4918423712"' in response.data
    assert b'id="ad-container"' in response.data
    assert b"Remove Shadows" in response.data
    assert b"https://sackofhacks.com/" in response.data
    assert b"https://sackofhacks.com/logo-prep/" in response.data
    assert b"https://vovchak.io/" not in response.data


def test_home_page_uses_reverse_proxy_prefix(client):
    response = client.get("/", headers={"X-Forwarded-Prefix": "/pdf-cleaner"})

    assert response.status_code == 200
    assert b'data-app-base="/pdf-cleaner"' in response.data
    assert b'href="/pdf-cleaner/static/style.css?v=11"' in response.data
    assert b'src="/pdf-cleaner/static/script.js?v=7"' in response.data


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


def test_load_pdf_rejects_page_over_pixel_limit(client, monkeypatch):
    monkeypatch.setitem(app.config, "MAX_PAGE_PIXELS", 100)
    document = pymupdf.open()
    document.new_page(width=20, height=20)

    response = client.post(
        "/load_pdf",
        data={"pdf": (io.BytesIO(document.tobytes()), "large-page.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "page 1 exceeds the maximum allowed size of 100 pixels" in response.get_json()["error"]


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


def test_save_pdf_applies_page_order_and_deletion(client):
    source_pdf = make_labeled_pdf(["first page", "second page", "third page"])
    loaded = client.post(
        "/load_pdf",
        data={"pdf": (io.BytesIO(source_pdf), "ordered.pdf")},
        content_type="multipart/form-data",
    )
    assert loaded.status_code == 200

    response = client.post(
        "/save_pdf",
        json={"quality": 80, "changedPages": [], "pageOrder": [2, 0]},
    )

    assert response.status_code == 200
    saved_pdf = pymupdf.open(stream=response.data, filetype="pdf")
    assert len(saved_pdf) == 2
    assert "third page" in saved_pdf[0].get_text()
    assert "first page" in saved_pdf[1].get_text()


def test_save_pdf_maps_edited_page_by_original_index_after_reordering(client):
    source_pdf = make_labeled_pdf(["first page", "second page"])
    loaded = client.post(
        "/load_pdf",
        data={"pdf": (io.BytesIO(source_pdf), "reordered-edit.pdf")},
        content_type="multipart/form-data",
    )
    assert loaded.status_code == 200
    assert client.post("/rotate/1/left").status_code == 200

    response = client.post(
        "/save_pdf",
        json={"quality": 80, "changedPages": [0], "pageOrder": [1, 0]},
    )

    assert response.status_code == 200
    saved_pdf = pymupdf.open(stream=response.data, filetype="pdf")
    assert len(saved_pdf) == 2
    assert not saved_pdf[0].get_text().strip()
    assert "first page" in saved_pdf[1].get_text()


@pytest.mark.parametrize(
    ("page_order", "error"),
    [
        ([], "Page order must contain unique non-negative page indexes."),
        ([0, 0], "Page order must contain unique non-negative page indexes."),
        ([-1], "Page order must contain unique non-negative page indexes."),
        ([3], "A page order index is out of range."),
        ([True], "Page order must contain unique non-negative page indexes."),
    ],
)
def test_save_pdf_rejects_invalid_page_order(client, monkeypatch, page_order, error):
    page = Image.new("RGB", (2, 2), "white")
    assert load_test_pages(client, monkeypatch, [page, page, page]).status_code == 200

    response = client.post(
        "/save_pdf",
        json={"changedPages": [], "pageOrder": page_order},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == error


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


def test_enhance_supports_shadow_removal(client, monkeypatch):
    page = Image.new("RGB", (2, 2), "white")
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200
    processed = []

    def remove_shadows(image):
        processed.append(image)
        return Image.new("RGB", image.size, "gray")

    monkeypatch.setattr(
        app_module.ImageProcessor,
        "remove_shadows",
        staticmethod(remove_shadows),
    )
    response = client.post("/enhance/0/remove_shadows/1")

    assert response.status_code == 200
    assert len(processed) == 1
    assert decode_preview(response).getpixel((0, 0)) == (128, 128, 128)


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


def test_payments_are_disabled_without_complete_configuration(client, monkeypatch):
    monkeypatch.setitem(app.config, "PAYMENTS_ENABLED", True)

    response = client.post("/billing/checkout")

    assert response.status_code == 503
    assert response.get_json()["error"] == "Payments are not configured yet."


def test_billing_routes_return_clear_error_without_loaded_pdf(client, monkeypatch):
    configure_payments(monkeypatch)

    status = client.get("/billing/status")
    checkout = client.post("/billing/checkout")

    assert status.status_code == 404
    assert checkout.status_code == 404
    assert status.get_json()["error"] == "No PDF is loaded for this session."
    assert checkout.get_json()["error"] == "No PDF is loaded for this session."


def test_checkout_uses_fixed_server_configured_price(client, monkeypatch):
    configure_payments(monkeypatch)
    page = Image.new("RGB", (2, 2), "white")
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200
    captured = {}

    class FakeCheckoutSession:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            return type("Checkout", (), {"url": "https://checkout.stripe.test/session"})()

    monkeypatch.setattr(app_module.stripe.checkout, "Session", FakeCheckoutSession)
    response = client.post("/billing/checkout")

    assert response.status_code == 200
    assert response.get_json()["url"] == "https://checkout.stripe.test/session"
    assert captured["line_items"][0]["price_data"]["currency"] == "eur"
    assert captured["line_items"][0]["price_data"]["unit_amount"] == 99
    assert captured["mode"] == "payment"
    assert captured["managed_payments"] == {"enabled": False}
    assert captured["metadata"]["session_id"] == captured["client_reference_id"]
    assert captured["metadata"]["product"] == app_module.PAYMENT_PRODUCT_ID
    assert len(captured["metadata"]["document_hash"]) == 64
    assert captured["success_url"] == (
        "https://sackofhacks.com/pdf-cleaner/billing/success"
        "?checkout_session_id={CHECKOUT_SESSION_ID}"
    )
    assert captured["cancel_url"] == (
        "https://sackofhacks.com/pdf-cleaner/?payment=cancelled"
    )


def test_webhook_grants_entitlement_only_after_verified_paid_checkout(
    client, monkeypatch
):
    configure_payments(monkeypatch)
    page = Image.new("RGB", (2, 2), "white")
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200
    checkout_values = {}

    class FakeCheckoutSession:
        @staticmethod
        def create(**kwargs):
            checkout_values.update(kwargs)
            return type("Checkout", (), {"url": "https://checkout.stripe.test/session"})()

    monkeypatch.setattr(app_module.stripe.checkout, "Session", FakeCheckoutSession)
    assert client.post("/billing/checkout").status_code == 200

    checkout_id = "cs_test_paid"
    event_checkout = app_module.stripe.StripeObject.construct_from(
        {
            "id": checkout_id,
            "mode": "payment",
            "payment_status": "paid",
            "client_reference_id": checkout_values["client_reference_id"],
            "metadata": checkout_values["metadata"],
        },
        "sk_test_configured",
    )
    monkeypatch.setattr(
        app_module.stripe.Webhook,
        "construct_event",
        lambda *args, **kwargs: {
            "type": "checkout.session.completed",
            "data": {"object": event_checkout},
        },
    )
    response = client.post(
        "/billing/webhook",
        data=b"verified payload",
        headers={"Stripe-Signature": "verified"},
    )

    assert response.status_code == 200
    status = client.get("/billing/status")
    assert status.get_json()["enabled"] is True
    assert status.get_json()["paid"] is True


def test_success_redirect_verifies_checkout_and_grants_entitlement(
    client, monkeypatch
):
    configure_payments(monkeypatch)
    page = Image.new("RGB", (2, 2), "white")
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200
    checkout_values = {}

    class FakeCheckoutSession:
        @staticmethod
        def create(**kwargs):
            checkout_values.update(kwargs)
            return type("Checkout", (), {"url": "https://checkout.stripe.test/session"})()

        @staticmethod
        def retrieve(checkout_id):
            return app_module.stripe.StripeObject.construct_from(
                {
                    "id": checkout_id,
                    "mode": "payment",
                    "payment_status": "paid",
                    "client_reference_id": checkout_values["client_reference_id"],
                    "metadata": checkout_values["metadata"],
                },
                "sk_test_configured",
            )

    monkeypatch.setattr(app_module.stripe.checkout, "Session", FakeCheckoutSession)
    assert client.post("/billing/checkout").status_code == 200

    response = client.get(
        "/billing/success?checkout_session_id=cs_test_paid",
    )

    assert response.status_code == 200
    assert b"Payment verified" in response.data
    assert client.get("/billing/status").get_json()["paid"] is True


def test_webhook_rejects_invalid_signature(client, monkeypatch):
    configure_payments(monkeypatch)

    def reject_signature(*args, **kwargs):
        raise app_module.stripe.SignatureVerificationError(
            "bad signature",
            "invalid",
        )

    monkeypatch.setattr(app_module.stripe.Webhook, "construct_event", reject_signature)
    response = client.post(
        "/billing/webhook",
        data=b"tampered",
        headers={"Stripe-Signature": "invalid"},
    )

    assert response.status_code == 400


def test_unpaid_checkout_webhook_does_not_unlock_document(client, monkeypatch):
    configure_payments(monkeypatch)
    page = Image.new("RGB", (2, 2), "white")
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200
    event_checkout = {
        "id": "cs_test_unpaid",
        "mode": "payment",
        "payment_status": "unpaid",
        "client_reference_id": "wrong-session",
        "metadata": {
            "session_id": "wrong-session",
            "document_hash": "0" * 64,
        },
    }
    monkeypatch.setattr(
        app_module.stripe.Webhook,
        "construct_event",
        lambda *args, **kwargs: {
            "type": "checkout.session.completed",
            "data": {"object": event_checkout},
        },
    )

    response = client.post(
        "/billing/webhook",
        data=b"verified payload",
        headers={"Stripe-Signature": "verified"},
    )

    assert response.status_code == 200
    assert client.get("/billing/status").get_json()["paid"] is False


def test_large_document_requires_payment_when_billing_is_enabled(
    client, monkeypatch
):
    configure_payments(monkeypatch)
    pages = [Image.new("RGB", (2, 2), "white") for _ in range(21)]
    assert load_test_pages(client, monkeypatch, pages).status_code == 200

    response = client.post("/rotate/0/left")

    assert response.status_code == 402
    assert response.get_json()["payment_required"] is True


def test_oversized_document_requires_payment_when_billing_is_enabled(
    client, monkeypatch
):
    configure_payments(monkeypatch)
    page = Image.new("RGB", (2, 2), "white")
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200
    monkeypatch.setattr(
        app_module.PAGE_STORE,
        "source_pdf",
        lambda _: b"x" * (app_module.FREE_PDF_SIZE + 1),
    )

    response = client.post("/rotate/0/left")

    assert response.status_code == 402
    assert response.get_json()["payment_required"] is True


def test_batch_edits_allow_three_pages_but_require_payment_for_more(
    client, monkeypatch
):
    configure_payments(monkeypatch)
    page = Image.new("RGB", (4, 3), "white")
    assert load_test_pages(client, monkeypatch, [page.copy() for _ in range(4)]).status_code == 200

    allowed = client.post(
        "/batch_action",
        json={"type": "rotate", "direction": "left", "pages": [0, 1, 2]},
    )
    blocked = client.post(
        "/batch_action",
        json={"type": "rotate", "direction": "left", "pages": [0, 1, 2, 3]},
    )

    assert allowed.status_code == 200
    assert set(allowed.get_json()["previews"]) == {"0", "1", "2"}
    assert blocked.status_code == 402


def test_low_compression_quality_requires_payment_when_enabled(client, monkeypatch):
    configure_payments(monkeypatch)
    page = Image.new("RGB", (2, 2), "white")
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200
    assert client.post("/rotate/0/left").status_code == 200

    response = client.post(
        "/save_pdf",
        json={"changedPages": [0], "quality": 60},
    )

    assert response.status_code == 402
    assert response.get_json()["payment_required"] is True


def test_low_quality_without_edited_pages_does_not_require_payment(
    client, monkeypatch
):
    configure_payments(monkeypatch)
    page = Image.new("RGB", (2, 2), "white")
    assert load_test_pages(client, monkeypatch, [page]).status_code == 200

    response = client.post(
        "/save_pdf",
        json={"changedPages": [], "quality": 60},
    )

    assert response.status_code == 200
