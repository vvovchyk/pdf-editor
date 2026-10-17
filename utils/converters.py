import io
import base64

import cv2
import numpy as np

from PIL import Image

# ========================= HELPERS =========================

def pil_to_b64(img):
    """Convert PIL image to base64 string."""

    buf = io.BytesIO()

    img.save(
        buf,
        format="JPEG",
        quality=85
    )

    return base64.b64encode(
        buf.getvalue()
    ).decode("utf-8")


def b64_to_pil(b64data):
    """Convert base64 string to PIL image."""

    return Image.open(
        io.BytesIO(
            base64.b64decode(b64data)
        )
    ).convert("RGB")


def pil_to_cv(img):
    """Convert PIL image to OpenCV image."""

    return cv2.cvtColor(
        np.array(img),
        cv2.COLOR_RGB2BGR
    )


def cv_to_pil(img):
    """Convert OpenCV image to PIL image."""

    return Image.fromarray(
        cv2.cvtColor(
            img,
            cv2.COLOR_BGR2RGB
        )
    )