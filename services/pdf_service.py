import pymupdf
import io
from PIL import Image


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
    def save_pdf(source_pdf, changed_pages, quality):
        """Preserve unchanged source pages and rasterize only edited pages."""
        if not changed_pages:
            return source_pdf

        source = pymupdf.open(stream=source_pdf, filetype="pdf")
        output = pymupdf.open()

        for index in range(len(source)):
            image = changed_pages.get(str(index))
            if image is None:
                output.insert_pdf(source, from_page=index, to_page=index)
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