from flask import Flask, render_template, request, jsonify, send_file
import pymupdf
import io

from utils.converters import (
    pil_to_b64,
    b64_to_pil,
    pil_to_cv,
    cv_to_pil
)

from services.pdf_service import PdfService
from services.image_service import ImageProcessor

MAX_HISTORY = 20

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB

# Instead of storing base64 strings, store PIL images (much lighter)
ORIGINAL_PAGES = []
EDITED_PAGES = []

PAGE_STORE = {
    "original": [],
    "edited": []
}

# Store only single-page snapshots for undo/redo
UNDO_STACK = {}
REDO_STACK = {}

# Helper functions
def init_page_history(page):

    if page not in UNDO_STACK:
        UNDO_STACK[page] = []

    if page not in REDO_STACK:
        REDO_STACK[page] = []

def push_undo(page):

    init_page_history(page)

    UNDO_STACK[page].append(
        EDITED_PAGES[page].copy()
    )

    if len(UNDO_STACK[page]) > MAX_HISTORY:
        UNDO_STACK[page].pop(0)

    REDO_STACK[page].clear()
    
def get_page(page):
    return EDITED_PAGES[page]


def set_page(page, img):
    EDITED_PAGES[page] = img

def get_original_pages():
    return PAGE_STORE["original"]


def get_edited_pages():
    return PAGE_STORE["edited"]
# ========================= LOAD PDF =========================

@app.route("/load_pdf", methods=["POST"])
def load_pdf():
    global ORIGINAL_PAGES, EDITED_PAGES, UNDO_STACK, REDO_STACK

    # Read uploaded PDF
    pdf_file = request.files["pdf"]

    pages = PdfService.load_pdf(pdf_file)

    # Reset editor state
    get_original_pages().clear()
    get_edited_pages().clear()
    UNDO_STACK.clear()
    REDO_STACK.clear()

    for page in pages:
        get_original_pages().append(page)
        get_edited_pages().append(page.copy())

    pages_b64 = [
        pil_to_b64(img)
        for img in ORIGINAL_PAGES
    ]

    return jsonify({"pages": pages_b64})


# ========================= UNDO / REDO =========================

@app.route("/undo/<int:page>", methods=["POST"])
def undo(page):

    init_page_history(page)

    if not UNDO_STACK[page]:
        return jsonify({
            "preview": pil_to_b64(
                EDITED_PAGES[page]
            )
        })

    REDO_STACK[page].append(
        EDITED_PAGES[page].copy()
    )

    EDITED_PAGES[page] = UNDO_STACK[page].pop()

    return jsonify({
        "preview": pil_to_b64(
            EDITED_PAGES[page]
        )
    })


@app.route("/redo/<int:page>", methods=["POST"])
def redo(page):

    init_page_history(page)

    if not REDO_STACK[page]:
        return jsonify({
            "preview": pil_to_b64(
                EDITED_PAGES[page]
            )
        })

    UNDO_STACK[page].append(
        EDITED_PAGES[page].copy()
    )

    EDITED_PAGES[page] = REDO_STACK[page].pop()

    return jsonify({
        "preview": pil_to_b64(
            EDITED_PAGES[page]
        )
    })


# ========================= ENHANCEMENTS =========================

@app.route("/enhance/<int:page>/<string:mode>/<value>", methods=["POST"])
def enhance_page(page, mode, value):
    global EDITED_PAGES, UNDO_STACK, REDO_STACK

    init_page_history(page)

    push_undo(page)

    img = get_page(page)
    value = float(value)

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
    global EDITED_PAGES, UNDO_STACK, REDO_STACK

    data = request.json
    page = data["page"]
    start = data["start"]
    end = data["end"]
    
    
    # Stack for later use in undo/redo
    init_page_history(page)

    push_undo(page)

    img = get_page(page)

    cropped = ImageProcessor.crop(
        img,
        start,
        end
    )

    EDITED_PAGES[page] = cropped

    return jsonify({
        "preview": pil_to_b64(cropped)
    })


# ========================= SELECTION ENHANCE =========================

@app.route("/selection_enhance", methods=["POST"])
def selection_enhance():
    global EDITED_PAGES, UNDO_STACK, REDO_STACK

    data = request.json
    page = data["page"]
    start = data["start"]
    end = data["end"]
    # Stack for later use in undo/redo
    init_page_history(page)
    push_undo(page)

    img = get_page(page)

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
    global EDITED_PAGES, UNDO_STACK, REDO_STACK

    data = request.json
    page = data["page"]
    start = data["start"]
    end = data["end"]

    # Stack for later use in undo/redo
    init_page_history(page)
    push_undo(page)

    img = get_page(page)
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
    data = request.json

    pages_b64 = data["pages"]
    quality = int(data["quality"])

    pdf_bytes = PdfService.save_pdf(
        pages_b64,
        quality
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
