from datetime import UTC, datetime

import pytest

from app.drafts.identity import derive_sku, generate_draft_id


def test_generate_draft_id_uses_expected_format():
    draft_id = generate_draft_id(datetime(2026, 4, 11, 12, 30, tzinfo=UTC))

    assert draft_id.startswith("draft_20260411_")
    assert len(draft_id.split("_", 2)[2]) == 8


def test_derive_sku_is_deterministic():
    assert derive_sku("draft_20260411_ab12cd34") == "oi-draft-20260411-ab12cd34"


@pytest.mark.parametrize("draft_id", ["bad", "draft_20260411", "foo_20260411_ab12cd34"])
def test_derive_sku_rejects_invalid_draft_id(draft_id: str):
    with pytest.raises(ValueError):
        derive_sku(draft_id)
