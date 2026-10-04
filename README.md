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

## Tech Stack
- Python 3
- Flask
- PyMuPDF
- OpenCV
- Pillow
- Gunicorn (Render deployment)

## Deployment
This project is deployed on **Render** as a Web Service.

Build command:
pip install -r requirements.txt

Start command:
gunicorn app:app

## License
MIT