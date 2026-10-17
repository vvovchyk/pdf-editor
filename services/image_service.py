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