import numpy as np
from PIL import Image, ImageDraw

from services.image_service import ImageProcessor


def make_shadowed_scan():
    width, height = 240, 180
    background = np.tile(
        np.linspace(150, 235, width, dtype=np.uint8),
        (height, 1),
    )
    image = Image.fromarray(background).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.text((100, 75), "SCAN", fill=(25, 25, 25))
    return image


def test_remove_shadows_flattens_background_and_preserves_text():
    image = make_shadowed_scan()
    result = np.asarray(ImageProcessor.remove_shadows(image).convert("L"))
    original = np.asarray(image.convert("L"))

    background_before = original[20:40, :].mean(axis=0)
    background_after = result[20:40, :].mean(axis=0)

    assert background_after.std() < background_before.std() * 0.35
    assert result[80, 101:130].min() < 60
