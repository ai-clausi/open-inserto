from app.drafts.identity import derive_sku
from app.drafts.models import Draft, WorkflowStatus
from app.drafts.workflow import transition_draft


def make_draft() -> Draft:
    return Draft(id="draft_20260411_ab12cd34", sku=derive_sku("draft_20260411_ab12cd34"))


def test_valid_workflow_transition_updates_status():
    draft = make_draft()

    transition_draft(draft, WorkflowStatus.OFFER_CREATED)

    assert draft.workflow.status is WorkflowStatus.OFFER_CREATED


def test_invalid_workflow_transition_raises_error():
    draft = make_draft()

    try:
        transition_draft(draft, WorkflowStatus.PUBLISHED)
    except ValueError as exc:
        assert "Invalid workflow transition" in str(exc)
    else:
        raise AssertionError("Expected invalid workflow transition to fail")


def test_legacy_readiness_statuses_load_as_draft_lifecycle_status():
    draft = Draft.model_validate(
        {
            "id": "draft_legacy",
            "sku": "OIN-LEGACY",
            "workflow": {"status": "ready_for_marketplace"},
        }
    )

    assert draft.workflow.status is WorkflowStatus.DRAFT
