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
        return img.rotate(
            90 if direction == "left" else -90,
            expand=True
        )