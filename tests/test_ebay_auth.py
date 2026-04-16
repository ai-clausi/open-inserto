from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.db.init_db import initialize_database
from app.main import create_app
from app.marketplaces.ebay.auth import EbayAuthStore
from app.marketplaces.ebay.client import EbayClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'test.db'}")
    monkeypatch.setenv("EBAY_CLIENT_ID", "client-123")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret-123")
    monkeypatch.setenv("EBAY_RU_NAME", "open-inserto-sandbox")
    monkeypatch.setenv("EBAY_AUTH_CALLBACK_URL", "http://testserver/integrations/ebay/callback")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_connect_route_redirects_to_ebay_oauth(client: TestClient):
    response = client.post("/integrations/ebay/connect", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("https://auth.sandbox.ebay.com/oauth2/authorize?")
    assert "client_id=client-123" in response.headers["location"]
    assert "redirect_uri=open-inserto-sandbox" in response.headers["location"]


def test_callback_exchanges_code_and_persists_tokens(client: TestClient):
    settings = get_settings()
    auth_store = EbayAuthStore(settings.database_path)
    state = auth_store.issue_state()

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 7200,
                "token_type": "Bearer",
            },
        )
    )
    fake_ebay_client = EbayClient(settings, client=httpx.Client(transport=transport), auth_store=auth_store)

    from app.web import routes

    original = routes.EbayClient
    routes.EbayClient = lambda *args, **kwargs: fake_ebay_client
    try:
        response = client.get(f"/integrations/ebay/callback?code=abc123&state={state}")
    finally:
        routes.EbayClient = original
        fake_ebay_client.close()

    assert response.status_code == 200
    assert "eBay wurde erfolgreich verbunden" in response.text
    tokens = auth_store.get_tokens()
    assert tokens.access_token == "access-1"
    assert tokens.refresh_token == "refresh-1"


def test_refresh_token_from_store_is_used_for_access_token(tmp_path: Path):
    settings = Settings(
        project_dir=tmp_path,
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        ebay_client_id="client-123",
        ebay_client_secret="secret-123",
        ebay_ru_name="open-inserto-sandbox",
    )
    initialize_database(settings.database_path)
    auth_store = EbayAuthStore(settings.database_path)
    auth_store.save_tokens(
        type(
            "TokenData",
            (),
            {
                "access_token": None,
                "refresh_token": "refresh-stored",
                "expires_in": None,
                "token_type": "Bearer",
            },
        )()
    )

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "access_token": "fresh-access",
                "refresh_token": "fresh-refresh",
                "expires_in": 7200,
                "token_type": "Bearer",
            },
        )
    )
    client = EbayClient(settings, client=httpx.Client(transport=transport), auth_store=auth_store)
    try:
        token = client.get_access_token()
    finally:
        client.close()

    assert token.token == "fresh-access"
    stored = auth_store.get_tokens()
    assert stored.refresh_token == "fresh-refresh"
