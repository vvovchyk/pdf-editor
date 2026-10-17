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