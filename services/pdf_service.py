import pymupdf
import io
from PIL import Image

from utils.converters import b64_to_pil


class PdfService:

    @staticmethod
    def load_pdf(pdf_file):
        """Convert uploaded PDF into a list of PIL images."""

        pages = []

        doc = pymupdf.open(
            stream=pdf_file.read(),
            filetype="pdf"
        )

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
    def save_pdf(pages_b64, quality):
        """Build a PDF from edited page images."""
        new_pdf = pymupdf.open()
        
        for b64 in pages_b64:
            img = b64_to_pil(b64)
            # Compress image before embedding
            img.thumbnail(
                (img.width, img.height),
                Image.LANCZOS
            )

            buf = io.BytesIO()

            img.save(
                buf,
                format="JPEG",
                quality=quality
            )

            jpeg_bytes = buf.getvalue()

            rect = pymupdf.Rect(
                0,
                0,
                img.width,
                img.height
            )

            page = new_pdf.new_page(
                width=img.width,
                height=img.height
            )

            page.insert_image(
                rect,
                stream=jpeg_bytes
            )

        return new_pdf.tobytes()