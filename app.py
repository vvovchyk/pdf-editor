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
    EDITED_PAGES[page] = REDO_STACK.pop()

    return jsonify({"preview": pil_to_b64(EDITED_PAGES[page])})


# ========================= ENHANCEMENTS =========================

@app.route("/enhance/<int:page>/<string:mode>/<value>", methods=["POST"])
def enhance_page(page, mode, value):
    global EDITED_PAGES, UNDO_STACK, REDO_STACK

    UNDO_STACK.append(EDITED_PAGES[page].copy())
    REDO_STACK.clear()

    img = EDITED_PAGES[page]
    value = float(value)

    if mode == "contrast":
        img = ImageEnhance.Contrast(img).enhance(value)

    elif mode == "brightness":
        img = ImageEnhance.Brightness(img).enhance(value)

    elif mode == "sharpness":
        img = ImageEnhance.Sharpness(img).enhance(value)

    elif mode == "denoise":
        if value > 0:
            img = img.filter(ImageFilter.MedianFilter(size=int(value)))

    elif mode == "auto":
        img = ImageEnhance.Contrast(img).enhance(1.4)
        img = ImageEnhance.Sharpness(img).enhance(1.6)
        img = img.filter(ImageFilter.MedianFilter(size=3))

    elif mode == "remove_bg":
        cv = pil_to_cv(img)
        gray = cv2.cvtColor(cv, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        cv[thresh == 255] = (255, 255, 255)
        img = cv_to_pil(cv)

    elif mode == "deskew":
        cv = pil_to_cv(img)
        gray = cv2.cvtColor(cv, cv2.COLOR_BGR2GRAY)
        coords = np.column_stack(np.where(gray < 200))
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        (h, w) = cv.shape[:2]
        M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        rotated = cv2.warpAffine(cv, M, (w, h), flags=cv2.INTER_LINEAR)
        img = cv_to_pil(rotated)

    EDITED_PAGES[page] = img
    return jsonify({"preview": pil_to_b64(img)})


# ========================= ROTATE =========================

@app.route("/rotate/<int:page>/<string:direction>", methods=["POST"])
def rotate_page(page, direction):
    global EDITED_PAGES, UNDO_STACK, REDO_STACK

    UNDO_STACK.append(EDITED_PAGES[page].copy())
    REDO_STACK.clear()

    img = EDITED_PAGES[page]

    if direction == "left":
        img = img.rotate(90, expand=True)
    else:
        img = img.rotate(-90, expand=True)

    EDITED_PAGES[page] = img
    return jsonify({"preview": pil_to_b64(img)})


# ========================= CROP =========================

@app.route("/crop_page", methods=["POST"])
def crop_page():
    global EDITED_PAGES, UNDO_STACK, REDO_STACK

    data = request.json
    page = data["page"]
    start = data["start"]
    end = data["end"]

    UNDO_STACK.append(EDITED_PAGES[page].copy())
    REDO_STACK.clear()

    img = EDITED_PAGES[page]

    x1 = int(start["x"])
    y1 = int(start["y"])
    x2 = int(end["x"])
    y2 = int(end["y"])

    crop_box = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    cropped = img.crop(crop_box)

    EDITED_PAGES[page] = cropped
    return jsonify({"preview": pil_to_b64(cropped)})


# ========================= SELECTION ENHANCE =========================

@app.route("/selection_enhance", methods=["POST"])
def selection_enhance():
    global EDITED_PAGES, UNDO_STACK, REDO_STACK

    data = request.json
    page = data["page"]
    start = data["start"]
    end = data["end"]

    UNDO_STACK.append(EDITED_PAGES[page].copy())
    REDO_STACK.clear()

    img = EDITED_PAGES[page]
    cv = pil_to_cv(img)

    x1 = int(start["x"])
    y1 = int(start["y"])
    x2 = int(end["x"])
    y2 = int(end["y"])

    region = cv[min(y1, y2):max(y1, y2), min(x1, x2):max(x1, x2)]
    region = cv2.detailEnhance(region, sigma_s=10, sigma_r=0.15)
    cv[min(y1, y2):max(y1, y2), min(x1, x2):max(x1, x2)] = region

    img = cv_to_pil(cv)
    EDITED_PAGES[page] = img

    return jsonify({"preview": pil_to_b64(img)})


# ========================= CLEAR AREA =========================

@app.route("/clear_area", methods=["POST"])
def clear_area():
    global EDITED_PAGES, UNDO_STACK, REDO_STACK

    data = request.json
    page = data["page"]
    start = data["start"]
    end = data["end"]

    UNDO_STACK.append(EDITED_PAGES[page].copy())
    REDO_STACK.clear()

    img = EDITED_PAGES[page]
    cv = pil_to_cv(img)

    x1 = int(start["x"])
    y1 = int(start["y"])
    x2 = int(end["x"])
    y2 = int(end["y"])

    cv[min(y1, y2):max(y1, y2), min(x1, x2):max(x1, x2)] = (255, 255, 255)

    img = cv_to_pil(cv)
    EDITED_PAGES[page] = img

    return jsonify({"preview": pil_to_b64(img)})


# ========================= SAVE PDF =========================

@app.route("/save_pdf", methods=["POST"])
def save_pdf():
    data = request.json
    pages_b64 = data["pages"]
    quality = int(data["quality"])

    new_pdf = pymupdf.open()

    for b64 in pages_b64:
        img = b64_to_pil(b64)

        # Reduce RAM usage by shrinking image before embedding
        img.thumbnail((img.width, img.height), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        jpeg_bytes = buf.getvalue()

        rect = pymupdf.Rect(0, 0, img.width, img.height)
        page = new_pdf.new_page(width=img.width, height=img.height)
        page.insert_image(rect, stream=jpeg_bytes)

    pdf_bytes = new_pdf.tobytes()

    response = send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        download_name="cleaned.pdf"
    )

    return response


# ========================= INDEX =========================

@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
