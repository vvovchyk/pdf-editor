import cv2
import numpy as np
from PIL import ImageEnhance, ImageFilter

from utils.converters import cv_to_pil, pil_to_cv


class ImageProcessor:

    @staticmethod
    def contrast(img, value):
        return ImageEnhance.Contrast(img).enhance(value)

    @staticmethod
    def brightness(img, value):
        return ImageEnhance.Brightness(img).enhance(value)

    @staticmethod
    def sharpness(img, value):
        return ImageEnhance.Sharpness(img).enhance(value)

    @staticmethod
    def denoise(img, value):
        size = max(3, int(value))
        if size % 2 == 0:
            size += 1
        max_size = min(img.size)
        if max_size % 2 == 0:
            max_size -= 1
        if max_size < 3:
            return img.copy()
        size = min(size, max_size)

        return img.filter(
            ImageFilter.MedianFilter(size=size)
        )

    @staticmethod
    def rotate(img, direction):

        if direction == "left":
            return img.rotate(90, expand=True)

        return img.rotate(-90, expand=True)
        
    @staticmethod
    def crop(img, start, end):

        x1 = int(start["x"])
        y1 = int(start["y"])

        x2 = int(end["x"])
        y2 = int(end["y"])

        crop_box = (
            min(x1, x2),
            min(y1, y2),
            max(x1, x2),
            max(y1, y2)
        )

        return img.crop(crop_box)
        
    @staticmethod
    def auto(img):
        img = ImageProcessor.remove_shadows(img)
        img = ImageEnhance.Contrast(img).enhance(1.4)
        img = ImageEnhance.Sharpness(img).enhance(1.6)

        img = img.filter(
            ImageFilter.MedianFilter(size=3)
        )

        return img
        
    @staticmethod
    def deskew(img):

        cv = pil_to_cv(img)

        gray = cv2.cvtColor(cv, cv2.COLOR_BGR2GRAY)

        coords = np.column_stack(
            np.where(gray < 200)
        )

        angle = cv2.minAreaRect(coords)[-1]

        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        h, w = cv.shape[:2]

        M = cv2.getRotationMatrix2D(
            (w // 2, h // 2),
            angle,
            1.0
        )

        rotated = cv2.warpAffine(
            cv,
            M,
            (w, h),
            flags=cv2.INTER_LINEAR
        )

        return cv_to_pil(rotated)
    
    @staticmethod
    def remove_bg(img):
        """Remove light background from scanned page."""

        cv = pil_to_cv(ImageProcessor.remove_shadows(img))

        gray = cv2.cvtColor(cv, cv2.COLOR_BGR2GRAY)

        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

        cv[thresh == 255] = (255, 255, 255)

        return cv_to_pil(cv)

    @staticmethod
    def remove_shadows(img):
        """Flatten uneven scan lighting while preserving foreground color."""

        cv = pil_to_cv(img)
        gray = cv2.cvtColor(cv, cv2.COLOR_BGR2GRAY)
        height, width = gray.shape
        scale = min(height, width)
        kernel_size = max(3, scale // 20)
        if kernel_size % 2 == 0:
            kernel_size += 1
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (kernel_size, kernel_size),
        )
        paper = cv2.dilate(gray, kernel)
        paper = cv2.GaussianBlur(
            paper,
            (0, 0),
            sigmaX=max(1.0, scale / 20),
            sigmaY=max(1.0, scale / 20),
        )
        corrected_gray = cv2.divide(
            gray,
            np.maximum(paper, 1),
            scale=255,
        )
        scale_factor = corrected_gray.astype(np.float32) / np.maximum(gray, 1)
        corrected = np.clip(
            cv.astype(np.float32) * scale_factor[:, :, np.newaxis],
            0,
            255,
        ).astype(np.uint8)
        return cv_to_pil(corrected)
        
        
    @staticmethod
    def clear_area(img, start, end):

        cv = pil_to_cv(img)

        x1 = int(start["x"])
        y1 = int(start["y"])

        x2 = int(end["x"])
        y2 = int(end["y"])

        cv[
            min(y1, y2):max(y1, y2),
            min(x1, x2):max(x1, x2)
        ] = (255, 255, 255)

        return cv_to_pil(cv)
    
    @staticmethod
    def selection_enhance(img, start, end):

        cv = pil_to_cv(img)

        x1 = int(start["x"])
        y1 = int(start["y"])

        x2 = int(end["x"])
        y2 = int(end["y"])

        region = cv[
            min(y1, y2):max(y1, y2),
            min(x1, x2):max(x1, x2)
        ]

        region = cv2.detailEnhance(
            region,
            sigma_s=10,
            sigma_r=0.15
        )

        cv[
            min(y1, y2):max(y1, y2),
            min(x1, x2):max(x1, x2)
        ] = region

        return cv_to_pil(cv)
        
        