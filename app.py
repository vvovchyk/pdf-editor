import os
import secrets
import io
import math
import hashlib
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request, send_file, session
import pymupdf
import stripe
from werkzeug.exceptions import RequestEntityTooLarge

from services.pdf_service import (
    MAX_PAGE_PIXELS,
    MAX_TOTAL_PIXELS,
    PdfPageLimitError,
    PdfService,
)
from services.image_service import ImageProcessor
from services.page_store import PageStore
from utils.converters import cv_to_pil, pil_to_b64, pil_to_cv

MAX_HISTORY = 20
MAX_PDF_PAGES = 100
FREE_PDF_PAGES = 20
FREE_PDF_SIZE = 25 * 1024 * 1024
FREE_BATCH_PAGES = 3
FREE_MIN_QUALITY = 70
PAYMENT_AMOUNT_CENTS = 99
PAYMENT_CURRENCY = "eur"
PAYMENT_PRODUCT_ID = "pdf_document_unlock_v1"
ENHANCEMENT_MODES = {
    "contrast",
    "brightness",
    "sharpness",
    "denoise",
    "auto",
    "remove_bg",
    "deskew",
}
ENHANCEMENT_RANGES = {
    "contrast": (0.5, 2.5),
    "brightness": (0.5, 2.0),
    "sharpness": (0, 3),
    "denoise": (0, 5),
}

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB
app.config["MAX_PDF_PAGES"] = MAX_PDF_PAGES
app.config["MAX_PAGE_PIXELS"] = MAX_PAGE_PIXELS
app.config["MAX_TOTAL_PIXELS"] = MAX_TOTAL_PIXELS
app.config["PAYMENTS_ENABLED"] = os.environ.get("PAYMENTS_ENABLED", "").lower() == "true"
app.config["STRIPE_SECRET_KEY"] = os.environ.get("STRIPE_SECRET_KEY")
app.config["STRIPE_WEBHOOK_SECRET"] = os.environ.get("STRIPE_WEBHOOK_SECRET")
app.config["PUBLIC_BASE_URL"] = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
app.config["PAYMENT_PRICE_LABEL"] = "€0.99"

PAGE_STORE = PageStore(
    os.environ.get("PAGE_STORE_PATH", os.path.join(app.instance_path, "pdf_state.sqlite3"))
)
app.config["SECRET_KEY"] = (
    os.environ.get("FLASK_SECRET_KEY") or PAGE_STORE.get_or_create_secret_key()
)


def get_session_id():
    if "document_id" not in session:
        session["document_id"] = secrets.token_urlsafe(32)
    return session["document_id"]


def get_page(page):
    return PAGE_STORE.page(get_session_id(), page)


def set_page(page, img):
    PAGE_STORE.set_page(get_session_id(), page, img)


def push_undo(page):
    PAGE_STORE.push_undo(get_session_id(), page, MAX_HISTORY)


@app.errorhandler(IndexError)
@app.errorhandler(KeyError)
def handle_missing_document(error):
    return jsonify({"error": str(error)}), 404


@app.errorhandler(RequestEntityTooLarge)
def handle_request_too_large(error):
    return jsonify({"error": "The request exceeds the maximum allowed size."}), 413


class InvalidRequest(Exception):
    pass


class PaymentRequired(Exception):
    pass


@app.errorhandler(InvalidRequest)
def handle_invalid_request(error):
    return jsonify({"error": str(error)}), 400


@app.errorhandler(PaymentRequired)
def handle_payment_required(error):
    return jsonify({
        "error": str(error),
        "payment_required": True,
    }), 402


def payments_enabled():
    base_url = urlsplit(app.config.get("PUBLIC_BASE_URL", ""))
    return app.config["PAYMENTS_ENABLED"] and all(
        app.config.get(key)
        for key in (
            "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET",
            "PUBLIC_BASE_URL",
        )
    ) and base_url.scheme == "https" and bool(base_url.netloc)


def current_document(session_id):
    source_pdf = PAGE_STORE.source_pdf(session_id)
    document_hash = hashlib.sha256(source_pdf).hexdigest()
    paid = PAGE_STORE.has_entitlement(session_id, document_hash)
    page_count = PAGE_STORE.page_count(session_id)
    requires_purchase = (
        page_count > FREE_PDF_PAGES or len(source_pdf) > FREE_PDF_SIZE
    )
    return source_pdf, document_hash, paid, page_count, requires_purchase


def billing_status(session_id):
    source_pdf, _, paid, page_count, requires_purchase = current_document(session_id)
    enabled = payments_enabled()
    return {
        "enabled": enabled,
        "paid": paid,
        "requiresPurchase": enabled and requires_purchase and not paid,
        "pageCount": page_count,
        "sizeBytes": len(source_pdf),
        "freePageLimit": FREE_PDF_PAGES,
        "freeSizeLimit": FREE_PDF_SIZE,
        "freeBatchLimit": FREE_BATCH_PAGES,
        "freeMinimumQuality": FREE_MIN_QUALITY,
        "price": app.config["PAYMENT_PRICE_LABEL"],
    }


def require_document_access(session_id):
    _, _, paid, _, requires_purchase = current_document(session_id)
    if payments_enabled() and requires_purchase and not paid:
        raise PaymentRequired(
            "This document exceeds the free limits. Unlock it to continue."
        )


def require_batch_access(session_id, page_indexes):
    require_document_access(session_id)
    paid = current_document(session_id)[2]
    if payments_enabled() and len(page_indexes) > FREE_BATCH_PAGES and not paid:
        raise PaymentRequired(
            "Batch editing more than 3 pages requires unlocking this document."
        )


def apply_enhancement(image, mode, value):
    if mode == "contrast":
        return ImageProcessor.contrast(image, value)
    if mode == "brightness":
        return ImageProcessor.brightness(image, value)
    if mode == "sharpness":
        return ImageProcessor.sharpness(image, value)
    if mode == "denoise":
        return ImageProcessor.denoise(image, value) if value > 0 else image
    if mode == "auto":
        return ImageProcessor.auto(image)
    if mode == "remove_bg":
        return ImageProcessor.remove_bg(image)
    if mode == "deskew":
        return ImageProcessor.deskew(image)
    raise InvalidRequest("Unknown enhancement mode.")


def json_object():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise InvalidRequest("A JSON object is required.")
    return data


def selection_request():
    data = json_object()
    page = data.get("page")
    if type(page) is not int or page < 0:
        raise InvalidRequest("Page must be a non-negative integer.")

    start = data.get("start")
    end = data.get("end")
    if not isinstance(start, dict) or not isinstance(end, dict):
        raise InvalidRequest("Selection start and end coordinates are required.")

    coordinates = (start.get("x"), start.get("y"), end.get("x"), end.get("y"))
    if any(type(value) is not int for value in coordinates):
        raise InvalidRequest("Selection coordinates must be integers.")

    image = get_page(page)
    require_document_access(get_session_id())
    x1, y1, x2, y2 = coordinates
    if (
        min(x1, x2) < 0
        or min(y1, y2) < 0
        or max(x1, x2) > image.width
        or max(y1, y2) > image.height
        or x1 == x2
        or y1 == y2
    ):
        raise InvalidRequest("Selection coordinates are outside the page or empty.")

    return page, start, end, image


def numeric_value(value, field):
    if isinstance(value, bool):
        raise InvalidRequest(f"{field} must be a finite number.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise InvalidRequest(f"{field} must be a finite number.") from None
    if not math.isfinite(number):
        raise InvalidRequest(f"{field} must be a finite number.")
    return number


def grant_paid_checkout(checkout, expected_session_id):
    session_id, document_hash = validate_checkout_document(
        checkout,
        expected_session_id,
    )
    if checkout.get("payment_status") != "paid":
        raise InvalidRequest("The checkout payment is not complete.")
    PAGE_STORE.grant_entitlement(
        session_id,
        document_hash,
        checkout["id"],
    )


def stripe_resource_to_dict(resource):
    if isinstance(resource, stripe.StripeObject):
        return resource.to_dict()
    return resource


def validate_checkout_document(checkout, expected_session_id):
    metadata = checkout.get("metadata") or {}
    session_id = metadata.get("session_id")
    document_hash = metadata.get("document_hash")
    if (
        checkout.get("mode") != "payment"
        or metadata.get("product") != PAYMENT_PRODUCT_ID
        or checkout.get("client_reference_id") != session_id
        or session_id != expected_session_id
        or not isinstance(document_hash, str)
        or len(document_hash) != 64
        or any(character not in "0123456789abcdef" for character in document_hash)
    ):
        raise InvalidRequest("The payment could not be verified for this document.")
    return session_id, document_hash


# ========================= LOAD PDF =========================

@app.route("/load_pdf", methods=["POST"])
def load_pdf():
    pdf_file = request.files.get("pdf")
    if pdf_file is None:
        return jsonify({"error": "A PDF file is required."}), 400

    source_pdf = pdf_file.read()
    try:
        pages = PdfService.load_pdf(
            io.BytesIO(source_pdf),
            max_pages=app.config["MAX_PDF_PAGES"],
            max_page_pixels=app.config["MAX_PAGE_PIXELS"],
            max_total_pixels=app.config["MAX_TOTAL_PIXELS"],
        )
    except PdfPageLimitError as error:
        return jsonify({"error": str(error)}), 400
    except pymupdf.FileDataError:
        return jsonify({"error": "The uploaded file is not a valid PDF."}), 400
    if not pages:
        return jsonify({"error": "The uploaded PDF has no pages."}), 400
    alignment = PdfService.page_size_info(source_pdf)
    PAGE_STORE.reset(get_session_id(), source_pdf, pages)
    pages_b64 = [pil_to_b64(page) for page in pages]

    return jsonify({
        "pages": pages_b64,
        "alignment": alignment,
        "billing": billing_status(get_session_id()),
    })


@app.route("/align_pages", methods=["POST"])
def align_pages():
    session_id = get_session_id()
    source_pdf = PAGE_STORE.source_pdf(session_id)
    alignment = PdfService.page_size_info(source_pdf)
    if not alignment["needed"]:
        raise InvalidRequest("All pages already use the same paper size.")
    pages = PAGE_STORE.pages(session_id)
    require_batch_access(session_id, list(range(len(pages))))

    aligned_pages = [
        PdfService.align_image(
            page,
            alignment["targetWidth"],
            alignment["targetHeight"],
        )
        for page in pages
    ]

    for index, image in enumerate(aligned_pages):
        push_undo(index)
        set_page(index, image)

    return jsonify({
        "pages": [pil_to_b64(page) for page in aligned_pages],
        "format": alignment["format"],
    })


# ========================= UNDO / REDO =========================

@app.route("/undo/<int:page>", methods=["POST"])
def undo(page):
    session_id = get_session_id()
    get_page(page)
    require_document_access(session_id)
    image = PAGE_STORE.undo(session_id, page, MAX_HISTORY)
    return jsonify({"preview": pil_to_b64(image)})


@app.route("/redo/<int:page>", methods=["POST"])
def redo(page):
    session_id = get_session_id()
    get_page(page)
    require_document_access(session_id)
    image = PAGE_STORE.redo(session_id, page, MAX_HISTORY)
    return jsonify({"preview": pil_to_b64(image)})


# ========================= ENHANCEMENTS =========================

@app.route("/enhance/<int:page>/<string:mode>/<value>", methods=["POST"])
def enhance_page(page, mode, value):
    if mode not in ENHANCEMENT_MODES:
        raise InvalidRequest("Unknown enhancement mode.")
    value = numeric_value(value, "Enhancement value")
    if mode in ENHANCEMENT_RANGES:
        minimum, maximum = ENHANCEMENT_RANGES[mode]
        if not minimum <= value <= maximum:
            raise InvalidRequest(
                f"{mode.capitalize()} must be between {minimum} and {maximum}."
            )

    session_id = get_session_id()
    img = get_page(page)
    require_document_access(session_id)
    push_undo(page)
    img = apply_enhancement(img, mode, value)
    set_page(page, img)
    return jsonify({"preview": pil_to_b64(img)})


# ========================= ROTATE =========================

@app.route("/rotate/<int:page>/<string:direction>", methods=["POST"])
def rotate_page(page, direction):
    if direction not in {"left", "right"}:
        raise InvalidRequest("Rotation direction must be 'left' or 'right'.")

    session_id = get_session_id()
    img = get_page(page)
    require_document_access(session_id)
    push_undo(page)

    img = ImageProcessor.rotate(
        img,
        direction
    )

    set_page(page, img)

    return jsonify(
        {"preview": pil_to_b64(img)}
    )


@app.route("/batch_action", methods=["POST"])
def batch_action():
    data = json_object()
    page_indexes = data.get("pages")
    if (
        not isinstance(page_indexes, list)
        or not page_indexes
        or any(type(index) is not int or index < 0 for index in page_indexes)
        or len(set(page_indexes)) != len(page_indexes)
    ):
        raise InvalidRequest("Pages must be a list of unique non-negative indexes.")

    session_id = get_session_id()
    require_batch_access(session_id, page_indexes)
    page_count = PAGE_STORE.page_count(session_id)
    if any(index >= page_count for index in page_indexes):
        raise InvalidRequest("A page index is out of range.")

    action_type = data.get("type")
    if action_type == "enhance":
        mode = data.get("mode")
        if mode not in ENHANCEMENT_MODES:
            raise InvalidRequest("Unknown enhancement mode.")
        value = numeric_value(data.get("value"), "Enhancement value")
        if mode in ENHANCEMENT_RANGES:
            minimum, maximum = ENHANCEMENT_RANGES[mode]
            if not minimum <= value <= maximum:
                raise InvalidRequest(
                    f"{mode.capitalize()} must be between {minimum} and {maximum}."
                )
    elif action_type == "rotate":
        direction = data.get("direction")
        if direction not in {"left", "right"}:
            raise InvalidRequest("Rotation direction must be 'left' or 'right'.")
    else:
        raise InvalidRequest("Unsupported batch action.")

    previews = {}
    for page_index in page_indexes:
        push_undo(page_index)
        image = get_page(page_index)
        if action_type == "enhance":
            image = apply_enhancement(image, mode, value)
        else:
            image = ImageProcessor.rotate(image, direction)
        set_page(page_index, image)
        previews[str(page_index)] = pil_to_b64(image)

    return jsonify({"previews": previews})


@app.route("/billing/status", methods=["GET"])
def get_billing_status():
    try:
        return jsonify(billing_status(get_session_id()))
    except KeyError:
        return jsonify({"error": "No PDF is loaded for this session."}), 404


@app.route("/billing/checkout", methods=["POST"])
def create_billing_checkout():
    if not payments_enabled():
        return jsonify({"error": "Payments are not configured yet."}), 503
    session_id = get_session_id()
    try:
        _, document_hash, paid, _, _ = current_document(session_id)
    except KeyError:
        return jsonify({"error": "No PDF is loaded for this session."}), 404
    if paid:
        return jsonify({"error": "This document is already unlocked."}), 409

    stripe.api_key = app.config["STRIPE_SECRET_KEY"]
    base_url = app.config["PUBLIC_BASE_URL"]
    try:
        checkout = stripe.checkout.Session.create(
            mode="payment",
            managed_payments={"enabled": False},
            line_items=[{
                "price_data": {
                    "currency": PAYMENT_CURRENCY,
                    "unit_amount": PAYMENT_AMOUNT_CENTS,
                    "product_data": {
                        "name": "PDF Cleaner document unlock",
                        "description": "Unlock batch editing and higher compression for one PDF.",
                    },
                },
                "quantity": 1,
            }],
            client_reference_id=session_id,
            metadata={
                "session_id": session_id,
                "document_hash": document_hash,
                "product": PAYMENT_PRODUCT_ID,
            },
            success_url=f"{base_url}/billing/success?checkout_session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/?payment=cancelled",
        )
    except stripe.StripeError:
        app.logger.exception("Stripe checkout session creation failed.")
        return jsonify({"error": "Could not start checkout. Please try again later."}), 502

    return jsonify({"url": checkout.url})


@app.route("/billing/webhook", methods=["POST"])
def stripe_webhook():
    if not payments_enabled():
        return jsonify({"error": "Payments are not configured."}), 503

    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(
            request.get_data(),
            signature,
            app.config["STRIPE_WEBHOOK_SECRET"],
        )
    except (ValueError, stripe.SignatureVerificationError):
        return jsonify({"error": "Invalid Stripe webhook signature or payload."}), 400

    if event["type"] in {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
    }:
        checkout = stripe_resource_to_dict(event["data"]["object"])
        if checkout.get("payment_status") == "paid":
            try:
                grant_paid_checkout(
                    checkout,
                    checkout.get("client_reference_id"),
                )
            except (KeyError, InvalidRequest) as error:
                app.logger.warning("Rejected invalid paid checkout event: %s", error)
                return jsonify({"error": "The completed checkout metadata is invalid."}), 400

    return jsonify({"received": True})


@app.route("/billing/success", methods=["GET"])
def billing_success():
    if not payments_enabled():
        return jsonify({"error": "Payments are not configured."}), 503
    checkout_id = request.args.get("checkout_session_id", "")
    if not checkout_id or len(checkout_id) > 255:
        return jsonify({"error": "A valid checkout session is required."}), 400

    stripe.api_key = app.config["STRIPE_SECRET_KEY"]
    try:
        checkout = stripe.checkout.Session.retrieve(checkout_id)
    except stripe.StripeError:
        app.logger.exception("Stripe checkout verification failed.")
        return jsonify({"error": "Could not verify the payment yet."}), 502
    checkout = stripe_resource_to_dict(checkout)
    if checkout.get("payment_status") != "paid":
        try:
            validate_checkout_document(checkout, get_session_id())
        except InvalidRequest:
            return jsonify({"error": "The checkout does not match this browser session."}), 400
        return render_template("payment_success.html", payment_complete=False)
    try:
        grant_paid_checkout(checkout, get_session_id())
    except (KeyError, InvalidRequest):
        return jsonify({"error": "The payment is not complete or does not match this session."}), 400

    return render_template("payment_success.html", payment_complete=True)


# ========================= CROP =========================

@app.route("/crop_page", methods=["POST"])
def crop_page():
    page, start, end, img = selection_request()
    push_undo(page)

    cropped = ImageProcessor.crop(
        img,
        start,
        end
    )

    set_page(page, cropped)

    return jsonify({
        "preview": pil_to_b64(cropped)
    })


# ========================= SELECTION ENHANCE =========================

@app.route("/selection_enhance", methods=["POST"])
def selection_enhance():
    page, start, end, img = selection_request()
    push_undo(page)

    img = ImageProcessor.selection_enhance(
        img,
        start,
        end
    )

    set_page(page, img)

    return jsonify({
        "preview": pil_to_b64(img)
    })


# ========================= CLEAR AREA =========================

@app.route("/clear_area", methods=["POST"])
def clear_area():
    page, start, end, img = selection_request()

    push_undo(page)

    cv = pil_to_cv(img)

    x1 = int(start["x"])
    y1 = int(start["y"])
    x2 = int(end["x"])
    y2 = int(end["y"])

    cv[min(y1, y2):max(y1, y2), min(x1, x2):max(x1, x2)] = (255, 255, 255)

    img = cv_to_pil(cv)
    set_page(page, img)

    return jsonify({"preview": pil_to_b64(img)})


# ========================= SAVE PDF =========================

@app.route("/save_pdf", methods=["POST"])
def save_pdf():
    data = json_object()
    changed_indexes = data.get("changedPages", [])
    if not isinstance(changed_indexes, list) or any(
        type(index) is not int or index < 0 for index in changed_indexes
    ):
        return jsonify({"error": "Changed pages must be a list of page indexes."}), 400
    quality = max(10, min(95, int(numeric_value(data.get("quality", 80), "Quality"))))
    session_id = get_session_id()
    require_document_access(session_id)
    _, _, paid, _, _ = current_document(session_id)
    if payments_enabled() and quality < FREE_MIN_QUALITY and not paid and changed_indexes:
        raise PaymentRequired(
            "Quality below 70 requires unlocking this document."
        )
    edited_pages = PAGE_STORE.pages(session_id)
    page_order = data.get("pageOrder")
    if page_order is not None and (
        not isinstance(page_order, list)
        or not page_order
        or any(type(index) is not int or index < 0 for index in page_order)
        or len(set(page_order)) != len(page_order)
    ):
        return jsonify({"error": "Page order must contain unique non-negative page indexes."}), 400
    if page_order is None:
        page_order = list(range(len(edited_pages)))
    if any(index >= len(edited_pages) for index in page_order):
        return jsonify({"error": "A page order index is out of range."}), 400
    if any(index >= len(page_order) for index in changed_indexes):
        return jsonify({"error": "A changed page index is out of range."}), 400
    changed_pages = {
        str(index): edited_pages[page_order[index]]
        for index in set(changed_indexes)
    }

    pdf_bytes = PdfService.save_pdf(
        PAGE_STORE.source_pdf(get_session_id()),
        changed_pages,
        quality,
        page_order=page_order if "pageOrder" in data else None,
    )

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        download_name="cleaned.pdf"
    )


# ========================= INDEX =========================

@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
