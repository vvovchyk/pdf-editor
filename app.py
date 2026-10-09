from flask import Flask, render_template, request, jsonify, send_file
import pymupdf
import io
import base64
from PIL import Image, ImageEnhance, ImageFilter
import numpy as np
import cv2

app = Flask(__name__)

# Instead of storing base64 strings, store PIL images (much lighter)
ORIGINAL_PAGES = []
EDITED_PAGES = []

# Store only single-page snapshots for undo/redo
UNDO_STACK = []
REDO_STACK = []


# ========================= HELPERS =========================

def pil_to_b64(img):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def b64_to_pil(b64data):
    return Image.open(io.BytesIO(base64.b64decode(b64data))).convert("RGB")


def pil_to_cv(img):
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def cv_to_pil(img):
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


# ========================= LOAD PDF =========================

@app.route("/load_pdf", methods=["POST"])
def load_pdf():
    global ORIGINAL_PAGES, EDITED_PAGES, UNDO_STACK, REDO_STACK

    pdf_file = request.files["pdf"]
    doc = pymupdf.open(stream=pdf_file.read(), filetype="pdf")

    ORIGINAL_PAGES.clear()
    EDITED_PAGES.clear()
    UNDO_STACK.clear()
    REDO_STACK.clear()

    for i in range(len(doc)):
        page = doc.load_page(i)

        # Render at normal resolution (Matrix(1,1)) to reduce RAM
        pix = page.get_pixmap(matrix=pymupdf.Matrix(1, 1))
        img = Image.open(io.BytesIO(pix.pil_tobytes(format="PNG"))).convert("RGB")

        ORIGINAL_PAGES.append(img)
        EDITED_PAGES.append(img.copy())

    # Convert only for sending to browser
    pages_b64 = [pil_to_b64(img) for img in ORIGINAL_PAGES]
    return jsonify({"pages": pages_b64})


# ========================= UNDO / REDO =========================

@app.route("/undo/<int:page>", methods=["POST"])
def undo(page):
    global EDITED_PAGES, UNDO_STACK, REDO_STACK

    if not UNDO_STACK:
        return jsonify({"preview": pil_to_b64(EDITED_PAGES[page])})

    REDO_STACK.append(EDITED_PAGES[page].copy())
    EDITED_PAGES[page] = UNDO_STACK.pop()

    return jsonify({"preview": pil_to_b64(EDITED_PAGES[page])})


@app.route("/redo/<int:page>", methods=["POST"])
def redo(page):
    global EDITED_PAGES, UNDO_STACK, REDO_STACK

    if not REDO_STACK:
        return jsonify({"preview": pil_to_b64(EDITED_PAGES[page])})

    UNDO_STACK.append(EDITED_PAGES[page].copy())
    EDITED_PAGES[page] =