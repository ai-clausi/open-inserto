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
        if request.url.path.endswith("/get_item_aspects_for_category"):
            return httpx.Response(
                200,
                json={
                    "aspects": [
                        {
                            "localizedAspectName": "Breite",
                            "aspectConstraint": {
                                "aspectRequired": True,
                                "aspectMode": "FREE_TEXT",
                                "aspectDataType": "STRING",
                            },
                        },
                        {
                            "localizedAspectName": "Marke",
                            "aspectConstraint": {"aspectRequired": False},
                        },
                    ]
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = EbayClient(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        token = client.get_application_access_token()
        category_tree_id = client.get_default_category_tree_id(token)
        suggestions = client.get_category_suggestions(token, category_tree_id=category_tree_id, query="Spielkonsole")
        aspects = client.get_item_aspects_for_category(token, category_tree_id=category_tree_id, category_id="139971")
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
    assert aspects[0]["name"] == "Breite"
    assert aspects[0]["required"] is True


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
    assert len(resolution["suggestions"]) == 1


def test_resolve_category_suggestion_ranks_matching_audio_category_above_bad_first_result(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path, mode="live")
    draft = Draft(
        id="draft_taxonomy",
        sku="OIN-TAX",
        listing={
            "title": "Bose SoundTouch 10 wireless music system",
            "brand": "Bose",
            "model": "SoundTouch 10",
            "categorySuggestion": "Audio, TV & Video > Lautsprecher > WLAN-Lautsprecher",
        },
    )

    class FakeClient:
        def __init__(self, settings):
            self.settings = settings

        def get_application_access_token(self):
            return object()

        def get_default_category_tree_id(self, access_token):
            return "77"

        def get_category_suggestions(self, access_token, *, category_tree_id: str, query: str):
            return [
                {"id": "8955", "name": "Aufkleber", "path": "Sammeln & Seltenes > Reklame & Werbung > Werbeartikel > Aufkleber"},
                {"id": "163768", "name": "TV-Hauptplatinen & -Teile", "path": "TV, Video & Audio > TV- & Heim-Audio-Teile > TV-Hauptplatinen & -Teile"},
                {"id": "14990", "name": "Lautsprecher & Subwoofer", "path": "TV, Video & Audio > Heim-Audio & HiFi > Lautsprecher & Subwoofer"},
                {"id": "61395", "name": "Sonstige", "path": "TV, Video & Audio > TV- & Heim-Audio-Zubehör > Sonstige"},
            ]

        def close(self):
            return None

    monkeypatch.setattr("app.marketplaces.ebay.taxonomy.EbayClient", FakeClient)

    resolve_category_suggestion_for_draft(draft, settings)
    resolution = get_category_resolution(draft)

    assert draft.listing.category_suggestion == "14990"
    assert resolution["selected_name"] == "Lautsprecher & Subwoofer"
    assert resolution["suggestions"][0]["id"] == "14990"


def test_resolve_category_suggestion_keeps_user_review_when_confidence_is_low(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path, mode="live")
    draft = Draft(
        id="draft_taxonomy",
        sku="OIN-TAX",
        listing={
            "title": "Bose SoundTouch 10 wireless music system",
            "brand": "Bose",
            "model": "SoundTouch 10",
            "categorySuggestion": "Aufkleber",
        },
    )

    class FakeClient:
        def __init__(self, settings):
            self.settings = settings

        def get_application_access_token(self):
            return object()

        def get_default_category_tree_id(self, access_token):
            return "77"

        def get_category_suggestions(self, access_token, *, category_tree_id: str, query: str):
            if query == "Aufkleber":
                return [
                    {
                        "id": "8955",
                        "name": "Aufkleber",
                        "path": "Sammeln & Seltenes > Reklame & Werbung > Werbeartikel > Aufkleber",
                    }
                ]
            return []

        def close(self):
            return None

    monkeypatch.setattr("app.marketplaces.ebay.taxonomy.EbayClient", FakeClient)

    resolve_category_suggestion_for_draft(draft, settings)
    resolution = get_category_resolution(draft)

    assert draft.listing.category_suggestion == "Aufkleber"
    assert resolution["state"] == "needs_selection"
    assert resolution["selected_id"] == ""
    assert resolution["suggestions"][0]["id"] == "8955"


def test_resolve_category_suggestion_uses_later_product_query_when_initial_hint_is_bad(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path, mode="live")
    draft = Draft(
        id="draft_taxonomy",
        sku="OIN-TAX",
        listing={
            "title": "Bose SoundTouch 10 wireless music system",
            "brand": "Bose",
            "model": "SoundTouch 10",
            "categorySuggestion": "Aufkleber",
        },
    )

    class FakeClient:
        def __init__(self, settings):
            self.settings = settings

        def get_application_access_token(self):
            return object()

        def get_default_category_tree_id(self, access_token):
            return "77"

        def get_category_suggestions(self, access_token, *, category_tree_id: str, query: str):
            if query == "Aufkleber":
                return [
                    {
                        "id": "8955",
                        "name": "Aufkleber",
                        "path": "Sammeln & Seltenes > Reklame & Werbung > Werbeartikel > Aufkleber",
                    }
                ]
            if "Bose" in query:
                return [
                    {
                        "id": "14990",
                        "name": "Lautsprecher & Subwoofer",
                        "path": "TV, Video & Audio > Heim-Audio & HiFi > Lautsprecher & Subwoofer",
                    }
                ]
            return []

        def close(self):
            return None

    monkeypatch.setattr("app.marketplaces.ebay.taxonomy.EbayClient", FakeClient)

    resolve_category_suggestion_for_draft(draft, settings)
    resolution = get_category_resolution(draft)

    assert draft.listing.category_suggestion == "14990"
    assert resolution["state"] == "resolved"
    assert resolution["selected_name"] == "Lautsprecher & Subwoofer"
    assert resolution["suggestions"][0]["id"] == "14990"


def test_resolve_category_suggestion_reranks_existing_auto_resolved_numeric_id(tmp_path: Path):
    settings = make_settings(tmp_path, mode="live")
    draft = Draft(
        id="draft_taxonomy",
        sku="OIN-TAX",
        listing={
            "title": "Bose SoundTouch 10 wireless music system",
            "brand": "Bose",
            "model": "SoundTouch 10",
            "categorySuggestion": "8955",
            "attributes": {
                "ebayCategory": {
                    "state": "resolved",
                    "query": "Audio, TV & Video > Lautsprecher > WLAN-Lautsprecher",
                    "original_query": "Audio, TV & Video > Lautsprecher > WLAN-Lautsprecher",
                    "selected_id": "8955",
                    "selected_name": "Aufkleber",
                    "selected_path": "Sammeln & Seltenes > Reklame & Werbung > Werbeartikel > Aufkleber",
                    "suggestions": [
                        {"id": "8955", "name": "Aufkleber", "path": "Sammeln & Seltenes > Reklame & Werbung > Werbeartikel > Aufkleber"},
                        {"id": "14990", "name": "Lautsprecher & Subwoofer", "path": "TV, Video & Audio > Heim-Audio & HiFi > Lautsprecher & Subwoofer"},
                    ],
                    "message": "",
                }
            },
        },
    )

    resolve_category_suggestion_for_draft(draft, settings)
    resolution = get_category_resolution(draft)

    assert draft.listing.category_suggestion == "14990"
    assert resolution["selected_name"] == "Lautsprecher & Subwoofer"


def test_resolve_category_suggestion_uses_path_leaf_and_updates_draft_with_numeric_id(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path, mode="sandbox")
    draft = Draft(
        id="draft_taxonomy",
        sku="OIN-TAX",
        listing={
            "title": "HP Omen W9S97AA Monitor",
            "brand": "HP",
            "model": "Omen W9S97AA",
            "categorySuggestion": "Computer & Zubehör > Monitore",
        },
    )
    queries: list[str] = []

    class FakeClient:
        def __init__(self, settings):
            self.settings = settings

        def get_application_access_token(self):
            return object()

        def get_default_category_tree_id(self, access_token):
            return "77"

        def get_category_suggestions(self, access_token, *, category_tree_id: str, query: str):
            queries.append(query)
            if query == "Monitore":
                return [{"id": "80053", "name": "Monitore", "path": "Computer, Tablets & Netzwerk > Monitore"}]
            return []

        def close(self):
            return None

    monkeypatch.setattr("app.marketplaces.ebay.taxonomy.EbayClient", FakeClient)

    resolve_category_suggestion_for_draft(draft, settings)
    resolution = get_category_resolution(draft)

    assert "Monitore" in queries
    assert draft.listing.category_suggestion == "80053"
    assert resolution["state"] == "resolved"
    assert resolution["query"] == "Monitore"
    assert resolution["original_query"] == "Computer & Zubehör > Monitore"
    assert resolution["selected_path"] == "Computer, Tablets & Netzwerk > Monitore"


def test_resolve_category_suggestion_shows_unscored_ebay_results_without_auto_selecting(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path, mode="live")
    draft = Draft(
        id="draft_taxonomy",
        sku="OIN-TAX",
        listing={
            "title": "Magic Mouse A1657 - MK2E3Z/A",
            "brand": "Apple",
            "model": "A1657",
            "categorySuggestion": "Computer Zubehör > Eingabegeräte > Mäuse",
        },
    )

    class FakeClient:
        def __init__(self, settings):
            self.settings = settings

        def get_application_access_token(self):
            return object()

        def get_default_category_tree_id(self, access_token):
            return "77"

        def get_category_suggestions(self, access_token, *, category_tree_id: str, query: str):
            return [
                {"id": "30108", "name": "Fahrradcomputer & GPS", "path": "Sport > Radsport > Fahrradelektronik > Fahrradcomputer & GPS"},
                {"id": "261186", "name": "Bücher", "path": "Bücher & Zeitschriften > Bücher"},
            ]

        def get_item_aspects_for_category(self, access_token, *, category_tree_id: str, category_id: str):
            return []

        def close(self):
            return None

    monkeypatch.setattr("app.marketplaces.ebay.taxonomy.EbayClient", FakeClient)

    resolve_category_suggestion_for_draft(draft, settings)
    resolution = get_category_resolution(draft)

    assert draft.listing.category_suggestion == "Computer Zubehör > Eingabegeräte > Mäuse"
    assert resolution["state"] == "needs_selection"
    assert resolution["suggestions"][0]["id"] == "30108"
    assert "nicht sicher automatisch bewerten" in resolution["message"]


def test_resolve_category_suggestion_uses_hair_styling_category_for_lockenstab(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path, mode="live")
    draft = Draft(
        id="draft_taxonomy",
        sku="OIN-TAX",
        listing={
            "title": "Lockenstab",
            "categorySuggestion": "Lockenstab",
        },
    )

    class FakeClient:
        def __init__(self, settings):
            self.settings = settings

        def get_application_access_token(self):
            return object()

        def get_default_category_tree_id(self, access_token):
            return "77"

        def get_category_suggestions(self, access_token, *, category_tree_id: str, query: str):
            return [
                {
                    "id": "177659",
                    "name": "Lockenstäbe & Glätteisen",
                    "path": "Beauty & Gesundheit > Haarpflege & Styling > Elektrische Haarstyling Geräte > Lockenstäbe & Glätteisen",
                }
            ]

        def get_item_aspects_for_category(self, access_token, *, category_tree_id: str, category_id: str):
            return []

        def close(self):
            return None

    monkeypatch.setattr("app.marketplaces.ebay.taxonomy.EbayClient", FakeClient)

    resolve_category_suggestion_for_draft(draft, settings)
    resolution = get_category_resolution(draft)

    assert draft.listing.category_suggestion == "177659"
    assert resolution["state"] == "resolved"
    assert resolution["selected_name"] == "Lockenstäbe & Glätteisen"


def test_resolve_category_suggestion_marks_missing_config(tmp_path: Path):
    settings = make_settings(tmp_path, mode="sandbox")
    settings.ebay_client_id = None
    settings.ebay_client_secret = None
    draft = Draft(id="draft_taxonomy", sku="OIN-TAX", listing={"categorySuggestion": "Spielkonsole"})

    resolve_category_suggestion_for_draft(draft, settings)
    resolution = get_category_resolution(draft)

    assert draft.listing.category_suggestion == "Spielkonsole"
    assert resolution["state"] == "config_missing"
    assert "Client-ID" in resolution["message"]
