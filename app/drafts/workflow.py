from __future__ import annotations

from app.drafts.models import Draft, WorkflowStatus, utc_now

ALLOWED_TRANSITIONS: dict[WorkflowStatus, set[WorkflowStatus]] = {
    WorkflowStatus.DRAFT: {WorkflowStatus.OFFER_CREATED, WorkflowStatus.ERROR},
    WorkflowStatus.OFFER_CREATED: {WorkflowStatus.PUBLISHED, WorkflowStatus.ERROR},
    WorkflowStatus.PUBLISHED: set(),
    WorkflowStatus.ERROR: {WorkflowStatus.DRAFT, WorkflowStatus.OFFER_CREATED},
}


def transition_draft(draft: Draft, new_status: WorkflowStatus) -> Draft:
    current_status = draft.workflow.status
    if current_status == new_status:
        return draft

    if new_status not in ALLOWED_TRANSITIONS[current_status]:
        msg = f"Invalid workflow transition: {current_status} -> {new_status}"
        raise ValueError(msg)

    draft.workflow.status = new_status
    draft.workflow.last_updated_at = utc_now()
    return draft
