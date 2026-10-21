import io
import math
import pymupdf

from PIL import Image, ImageOps

MAX_PAGE_PIXELS = 20_000_000
MAX_TOTAL_PIXELS = 100_000_000


class PdfPageLimitError(Exception):
    pass


class PdfService:
    @staticmethod
    def page_size_info(source_pdf):
        """Return detected page-size variation and the most common paper size."""
        document = pymupdf.open(stream=source_pdf, filetype="pdf")
        sizes = [(page.rect.width, page.rect.height) for page in document]
        groups = {}

        for width, height in sizes:
            key = (round(min(width, height)), round(max(width, height)))
            groups.setdefault(key, []).append((width, height))

        target_key = max(groups, key=lambda key: len(groups[key]))
        target_width, target_height = groups[target_key][0]
        label = PdfService._format_label(*target_key)
        return {
            "needed": len(groups) > 1,
            "format": label,
            "formatCount": len(groups),
            "targetWidth": target_width,
            "targetHeight": target_height,
        }

    @staticmethod
    def _format_label(width, height):
        known_formats = {
            (595, 842): "A4",
            (420, 595): "A5",
            (297, 420): "A6",
            (842, 1191): "A3",
            (612, 792): "Letter",
            (612, 1008): "Legal",
        }
        name = known_formats.get((width, height))
        dimensions = f"{width} × {height} pt"
        return f"{name} ({dimensions})" if name else dimensions

    @staticmethod
    def align_image(image, target_width, target_height):
        """Fit a page image onto the target paper size without cropping."""
        canvas_width = max(1, round(target_width))
        canvas_height = max(1, round(target_height))
        if image.width > image.height:
            canvas_width, canvas_height = canvas_height, canvas_width

        fitted = ImageOps.contain(
            image,
            (canvas_width, canvas_height),
            method=Image.Resampling.LANCZOS,
        )
        canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
        canvas.paste(
            fitted,
            ((canvas_width - fitted.width) // 2, (canvas_height - fitted.height) // 2),
        )
        return canvas

    @staticmethod
    def load_pdf(
        pdf_file,
        max_pages=None,
        max_page_pixels=MAX_PAGE_PIXELS,
        max_total_pixels=MAX_TOTAL_PIXELS,
    ):
        """Convert uploaded PDF into a list of PIL images."""

        doc = pymupdf.open(stream=pdf_file.read(), filetype="pdf")
        if max_pages is not None and len(doc) > max_pages:
            raise PdfPageLimitError(
                f"PDF exceeds the maximum allowed page count of {max_pages}."
            )

        total_pixels = 0
        for i in range(len(doc)):
            page = doc.load_page(i)
            rect = page.rect
            if (
                not math.isfinite(rect.width)
                or not math.isfinite(rect.height)
                or rect.width <= 0
                or rect.height <= 0
            ):
                raise PdfPageLimitError(
                    f"PDF page {i + 1} has invalid dimensions."
                )
            width = math.ceil(rect.width)
            height = math.ceil(rect.height)
            pixels = width * height
            if pixels > max_page_pixels:
                raise PdfPageLimitError(
                    f"PDF page {i + 1} exceeds the maximum allowed "
                    f"size of {max_page_pixels} pixels."
                )
            total_pixels += pixels
            if total_pixels > max_total_pixels:
                raise PdfPageLimitError(
                    f"PDF exceeds the maximum allowed total of "
                    f"{max_total_pixels} pixels."
                )
        pages = []
        for i in range(len(doc)):
            page = doc.load_page(i)
            # Render page at preview resolution
            pix = page.get_pixmap(
                matrix=pymupdf.Matrix(1, 1)
            )

            img = Image.open(
                io.BytesIO(
                    pix.pil_tobytes(format="PNG")
                )
            ).convert("RGB")

            pages.append(img)

        return pages
        
    @staticmethod
    def save_pdf(source_pdf, changed_pages, quality, page_order=None):
        """Preserve unchanged source pages and rasterize only edited pages."""
        if not changed_pages and page_order is None:
            return source_pdf

        source = pymupdf.open(stream=source_pdf, filetype="pdf")
        if not changed_pages and page_order == list(range(len(source))):
            return source_pdf
        output = pymupdf.open()

        source_indexes = page_order if page_order is not None else range(len(source))
        for output_index, source_index in enumerate(source_indexes):
            image = changed_pages.get(str(output_index))
            if image is None:
                output.insert_pdf(source, from_page=source_index, to_page=source_index)
                continue

            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality)

            page = output.new_page(
                width=image.width,
                height=image.height,
            )
            page.insert_image(page.rect, stream=buffer.getvalue())

        output.set_metadata(source.metadata)
        return output.tobytes()