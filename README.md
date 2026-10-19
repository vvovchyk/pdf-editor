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
- Optional one-time checkout to unlock batch editing for larger PDFs and higher compression quality

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
- Payment controls remain disabled unless `PAYMENTS_ENABLED=true` and Stripe API, webhook, and HTTPS public URL settings are configured. Checkout uses a fixed inline price of €0.99 per PDF.
- A responsive Google AdSense display unit is shown in the editor sidebar after AdSense serves it. The publisher consent message must be configured and published in AdSense; ads may not appear until site/ad-unit review and consent settings are effective.
- Unchanged pages retain their original PDF content. Edited pages are exported as JPEG images, so their text/vector content is rasterized.
- Multiple workers on one host can share the SQLite database. Multiple app instances need a shared database and storage location.

## Tests
Install development dependencies with `python -m pip install -r requirements-dev.txt`,
install Chromium for browser tests with `python -m playwright install chromium`,
then run the test suite with `python -m pytest -q`.

## One-time payments
Create and verify a Stripe account. The application creates a fixed one-time
EUR €0.99 Checkout line item for unlocking one PDF. Add these server environment
variables: `PAYMENTS_ENABLED=true`, `STRIPE_SECRET_KEY`,
`STRIPE_WEBHOOK_SECRET`, and
`PUBLIC_BASE_URL=https://pdfcleaner.vovchak.io`.
Register `https://pdfcleaner.vovchak.io/billing/webhook` in Stripe for the
`checkout.session.completed` and `checkout.session.async_payment_succeeded`
events. Store secret values only in the VPS or deployment secret manager,
never in source control. Payment restrictions remain off until all required
settings are present.

When enabled, documents above 20 pages or 25 MB, batch edits of more than 3
pages, and export quality below 70 require one-time unlocking. The document
entitlement is granted only after a verified Stripe checkout and is scoped to
the uploaded PDF and browser session.

## License
MIT