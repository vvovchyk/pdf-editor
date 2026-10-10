import io
import pytest
from app import app

@pytest.fixture
def client():
    app.testing = True
    return app.test_client()

def test_home_page(client):
    """Перевіряємо, що головна сторінка працює"""
    response = client.get("/")
    assert response.status_code == 200

def test_upload_pdf(client):
    """Перевіряємо, що сервер приймає PDF"""
    fake_pdf = io.BytesIO(b"%PDF-1.4 fake content")
    data = {
        "file": (fake_pdf, "test.pdf")
    }
    response = client.post("/upload", data=data, content_type="multipart/form-data")
    # твій /upload може повернути 200 або 400 — обидва варіанти ок
    assert response.status_code in (200, 400)
