from app.drafts.models import Draft, WorkflowStatus
from app.drafts.review import update_draft_from_review


def build_draft(*, with_images: bool = True) -> Draft:
    draft = Draft(id="draft_review1234", sku="OIN-REVIEW1234")
    if with_images:
        draft.source.images = [
            {
                "id": "img_1",
                "originalFilename": "front.jpg",
                "storagePath": "data/drafts/draft_review1234/images/normalized/01-normalized.jpg",
                "mimeType": "image/jpeg",
                "order": 1,
                "kind": "normalized",
            }
        ]
    return draft


def test_review_confirmation_marks_draft_ready_for_marketplace_when_core_fields_are_complete():
    draft = build_draft()

    update_draft_from_review(
        draft,
        title="Tischlampe",
        condition="gut",
        description="Voll funktionsfähig",
        included_items="Kabel",
        brand="NoName",
        model="L1",
        subtitle="Metall",
        category_suggestion="1234",
        hints="",
        confirm_fields=[],
        action="confirm",
    )

    assert draft.workflow.status is WorkflowStatus.READY_FOR_MARKETPLACE
    assert draft.workflow.needs_review is False
    assert draft.workflow.missing_information == []


def test_review_save_marks_draft_blocked_when_required_images_are_missing():
    draft = build_draft(with_images=False)

    update_draft_from_review(
        draft,
        title="Tischlampe",
        condition="gut",
        description="Voll funktionsfähig",
        included_items="Kabel",
        brand="NoName",
        model="L1",
        subtitle="Metall",
        category_suggestion="1234",
        hints="",
        confirm_fields=[],
        action="save",
    )

    assert draft.workflow.status is WorkflowStatus.BLOCKED
    assert draft.workflow.needs_review is True
    assert draft.workflow.missing_information == []
