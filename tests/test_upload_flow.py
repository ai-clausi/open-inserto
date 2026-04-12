from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'test.db'}")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def build_image_bytes(*, image_format: str = "JPEG", size: tuple[int, int] = (1200, 900), color=(64, 114, 255)) -> bytes:
    image = Image.new("RGB", size, color=color)
    buffer = BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def test_upload_page_renders(client: TestClient):
    response = client.get("/drafts/upload")

    assert response.status_code == 200
    assert "Mehrfach-Upload mit Vorschau" in response.text
    assert "Draft erstellen" in response.text


def test_post_upload_creates_draft_and_files(client: TestClient):
    files = [
        ("images", ("front.jpg", build_image_bytes(image_format="JPEG"), "image/jpeg")),
        ("images", ("back.png", build_image_bytes(image_format="PNG"), "image/png")),
    ]
    data = {
        "notes": "Leichte Gebrauchsspuren",
        "product_name": "Testgerät",
        "condition": "gebraucht",
        "accessories": "Netzteil",
        "hints": "Seriennummer verdeckt",
    }

    response = client.post("/drafts/upload", files=files, data=data, follow_redirects=False)

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/drafts/draft_")

    detail = client.get(location)
    assert detail.status_code == 200
    assert "Deine Angaben" in detail.text
    assert "Systemvorschlag" in detail.text
    assert "Freitext-Notizen" in detail.text
    assert "Leichte Gebrauchsspuren" in detail.text
    assert "Testgerät" in detail.text
    assert "classified" in detail.text
    assert "Netzteil" in detail.text
    assert "Seriennummer verdeckt" in detail.text
    assert "MVP-Heuristik" in detail.text
    assert "front.jpg" in detail.text
    assert "back.png" in detail.text

    settings = get_settings()
    originals = sorted(settings.data_dir.glob("drafts/*/images/originals/*"))
    normalized = sorted(settings.data_dir.glob("drafts/*/images/normalized/*"))
    assert len(originals) == 2
    assert len(normalized) == 2


def test_post_upload_without_images_returns_validation_error(client: TestClient):
    response = client.post("/drafts/upload", data={"notes": "Ohne Bild"})

    assert response.status_code == 400
    assert "Bitte mindestens ein Bild auswählen." in response.text


def test_post_upload_rejects_invalid_file_type(client: TestClient):
    response = client.post(
        "/drafts/upload",
        files=[("images", ("notes.txt", b"keine bilddatei", "text/plain"))],
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "nicht unterstützten Bildtyp" in response.text or "kein unterstütztes Bildformat" in response.text


def test_post_upload_rejects_too_small_images(client: TestClient):
    response = client.post(
        "/drafts/upload",
        files=[("images", ("small.jpg", build_image_bytes(size=(320, 240)), "image/jpeg"))],
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "mindestens 500px" in response.text
