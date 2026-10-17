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
        return img.filter(
            ImageFilter.MedianFilter(size=int(value))
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

        cv = pil_to_cv(img)

        gray = cv2.cvtColor(cv, cv2.COLOR_BGR2GRAY)

        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

        cv[thresh == 255] = (255, 255, 255)

        return cv_to_pil(cv)