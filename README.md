# PDF Editor

Simple online PDF cleaner that improves scanned pages, removes noise, enhances contrast, sharpness, and compresses documents.  
Built with **Flask**, **PyMuPDF**, **OpenCV**, and **Pillow**.

## Features
- Page-by-page preview
- Auto enhancement (contrast, sharpness, denoise)
- Manual controls: brightness, contrast, sharpness
- Crop tool
- Selection enhancement
- Clear area tool
- Rotate pages
- Deskew scanned pages
- Background removal
- Adjustable PDF compression
- Undo / Redo system
- Optional page-size alignment to the most common detected format
- Delete pages and reorder them before export

## Tech Stack
- Python 3
- Flask
- PyMuPDF
- OpenCV
- Pillow
- Gunicorn (VPS deployment)

## Deployment
The GitHub Actions workflow runs tests for pull requests targeting `main` and
pushes to `main`. A push to `main` is deployed to the VPS over SSH only after
the tests pass. Configure the `SSH_PRIVATE_KEY`, `SSH_USER`, and `SSH_HOST`
repository secrets for deployment. The VPS must have the repository checked
out at `/var/www/pdfcleaner` and a `pdfcleaner` systemd service configured.

Install dependencies with `python -m pip install -r requirements.txt` and run
the application with `gunicorn app:app`.

## Storage
- Session state is stored in SQLite at `instance/pdf_state.sqlite3` by default.
- Set `FLASK_SECRET_KEY` to a stable secret in production. `PAGE_STORE_PATH` can override the database path.
- Uploads are limited to 200 MB and 100 pages.
- Mixed page sizes are detected after upload. Users can align pages to the most common size or keep the original sizes; alignment preserves portrait/landscape orientation, fits and centers content without cropping.
- Unchanged pages retain their original PDF content. Edited pages are exported as JPEG images, so their text/vector content is rasterized.
- Multiple workers on one host can share the SQLite database. Multiple app instances need a shared database and storage location.

## Tests
Install development dependencies with `python -m pip install -r requirements-dev.txt`,
install Chromium for browser tests with `python -m playwright install chromium`,
then run the test suite with `python -m pytest -q`.

## License
MIT