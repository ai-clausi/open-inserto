from pathlib import Path

import httpx

from app.core.config import Settings
from app.drafts.models import Draft
from app.marketplaces.ebay.client import EbayClient
from app.marketplaces.ebay.taxonomy import get_category_resolution, resolve_category_suggestion_for_draft


def make_settings(tmp_path: Path, *, mode: str = "live") -> Settings:
    return Settings(
        project_dir=tmp_path,
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'open_inserto.db'}",
        ebay_mode=mode,
        ebay_marketplace_id="EBAY_DE",
        ebay_client_id="client-123",
        ebay_client_secret="secret-123",
    )


def test_ebay_client_fetches_taxonomy_category_suggestions(tmp_path: Path):
    settings = make_settings(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/identity/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "app-token", "token_type": "Bearer", "expires_in": 7200})
        if request.url.path.endswith("/commerce/taxonomy/v1/get_default_category_tree_id"):
            return httpx.Response(200, json={"categoryTreeId": "77"})
        if request.url.path.endswith("/get_category_suggestions"):
            return httpx.Response(
                200,
                json={
                    "categorySuggestions": [
                        {
                            "category": {"categoryId": "139971", "categoryName": "Konsolen"},
                            "categoryTreeNodeAncestors": [
                                {"categoryId": "139973", "categoryName": "Konsolen & Zubehör"},
                                {"categoryId": "1249", "categoryName": "PC- & Videospiele"},
                            ],
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = EbayClient(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        token = client.get_application_access_token()
        category_tree_id = client.get_default_category_tree_id(token)
        suggestions = client.get_category_suggestions(token, category_tree_id=category_tree_id, query="Spielkonsole")
    finally:
        client.close()

    assert token.token == "app-token"
    assert category_tree_id == "77"
    assert suggestions == [
        {
            "id": "139971",
            "name": "Konsolen",
            "path": "PC- & Videospiele > Konsolen & Zubehör > Konsolen",
        }
    ]


def test_resolve_category_suggestion_updates_draft_with_numeric_id(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path, mode="live")
    draft = Draft(id="draft_taxonomy", sku="OIN-TAX", listing={"categorySuggestion": "Spielkonsole"})

    class FakeClient:
        def __init__(self, settings):
            self.settings = settings

        def get_application_access_token(self):
            return object()

        def get_default_category_tree_id(self, access_token):
            return "77"

        def get_category_suggestions(self, access_token, *, category_tree_id: str, query: str):
            assert category_tree_id == "77"
            assert query == "Spielkonsole"
            return [
                {"id": "139971", "name": "Konsolen", "path": "Gaming > Konsolen"},
                {"id": "117042", "name": "Controller", "path": "Gaming > Zubehör > Controller"},
            ]

        def close(self):
            return None

    monkeypatch.setattr("app.marketplaces.ebay.taxonomy.EbayClient", FakeClient)

    resolve_category_suggestion_for_draft(draft, settings)
    resolution = get_category_resolution(draft)

    assert draft.listing.category_suggestion == "139971"
    assert resolution["state"] == "resolved"
    assert resolution["query"] == "Spielkonsole"
    assert resolution["selected_id"] == "139971"
    assert resolution["selected_name"] == "Konsolen"
    assert len(resolution["suggestions"]) == 2


def test_resolve_category_suggestion_marks_sandbox_lookup_as_unavailable(tmp_path: Path):
    settings = make_settings(tmp_path, mode="sandbox")
    draft = Draft(id="draft_taxonomy", sku="OIN-TAX", listing={"categorySuggestion": "Spielkonsole"})

    resolve_category_suggestion_for_draft(draft, settings)
    resolution = get_category_resolution(draft)

    assert draft.listing.category_suggestion == "Spielkonsole"
    assert resolution["state"] == "sandbox_unavailable"
    assert "Sandbox" in resolution["message"]
