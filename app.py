import os
import secrets
import io
import math

from flask import Flask, jsonify, render_template, request, send_file, session
import pymupdf
from werkzeug.exceptions import RequestEntityTooLarge

from services.pdf_service import PdfPageLimitError, PdfService
from services.image_service import ImageProcessor
from services.page_store import PageStore
from utils.converters import cv_to_pil, pil_to_b64, pil_to_cv

MAX_HISTORY = 20
MAX_PDF_PAGES = 100
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


@app.errorhandler(InvalidRequest)
def handle_invalid_request(error):
    return jsonify({"error": str(error)}), 400


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

    return jsonify({"pages": pages_b64, "alignment": alignment})


@app.route("/align_pages", methods=["POST"])
def align_pages():
    session_id = get_session_id()
    source_pdf = PAGE_STORE.source_pdf(session_id)
    alignment = PdfService.page_size_info(source_pdf)
    if not alignment["needed"]:
        raise InvalidRequest("All pages already use the same paper size.")
    pages = PAGE_STORE.pages(session_id)

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
    image = PAGE_STORE.undo(get_session_id(), page, MAX_HISTORY)
    return jsonify({"preview": pil_to_b64(image)})


@app.route("/redo/<int:page>", methods=["POST"])
def redo(page):
    image = PAGE_STORE.redo(get_session_id(), page, MAX_HISTORY)
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

    push_undo(page)

    img = get_page(page)

    if mode == "contrast":
        img = ImageProcessor.contrast(img, value)

    elif mode == "brightness":
        img = ImageProcessor.brightness(img, value)

    elif mode == "sharpness":
        img = ImageProcessor.sharpness(img, value)

    elif mode == "denoise":
        if value > 0:
            img = ImageProcessor.denoise(img, value)

    elif mode == "auto":
        img = ImageProcessor.auto(img)

    elif mode == "remove_bg":
        img = ImageProcessor.remove_bg(img)

    elif mode == "deskew":
        img = ImageProcessor.deskew(img)

    set_page(page, img)
    return jsonify({"preview": pil_to_b64(img)})


# ========================= ROTATE =========================

@app.route("/rotate/<int:page>/<string:direction>", methods=["POST"])
def rotate_page(page, direction):
    if direction not in {"left", "right"}:
        raise InvalidRequest("Rotation direction must be 'left' or 'right'.")

    push_undo(page)
    img = get_page(page)

    img = ImageProcessor.rotate(
        img,
        direction
    )

    set_page(page, img)

    return jsonify(
        {"preview": pil_to_b64(img)}
    )


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
    edited_pages = PAGE_STORE.pages(get_session_id())
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
