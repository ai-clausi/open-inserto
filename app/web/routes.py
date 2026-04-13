from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.drafts.analysis import HeuristicDraftAnalysisService, apply_analysis_result
from app.drafts.repository import DraftRepository
from app.drafts.models import WorkflowStatus
from app.drafts.review import (
    CORE_FIELDS,
    OPTIONAL_FIELDS,
    evaluate_review_state,
    get_confidence_notes,
    get_missing_core_fields,
    get_review_metadata,
    update_draft_from_review,
)
from app.drafts.upload_service import DraftUploadService, UploadAsset, UploadValidationError
from app.marketplaces.ebay.service import EbayMarketplaceService
from app.marketplaces.ebay.validation import collect_marketplace_notes, collect_marketplace_readiness_errors

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


EXTRA_FIELDS = [
    ("product_name", "Produktname"),
    ("condition", "Zustand"),
    ("accessories", "Zubehör"),
    ("hints", "Hinweise"),
]


def build_context(request: Request, **extra):
    settings = get_settings()
    context = {
        "request": request,
        "app_name": settings.app_name,
        "ebay_mode": settings.ebay_mode,
        "database_url": settings.database_url,
        "extra_fields": EXTRA_FIELDS,
    }
    context.update(extra)
    return context


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "environment": settings.app_env,
        "ebay_mode": settings.ebay_mode,
    }


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", build_context(request))


@router.get("/drafts/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    return templates.TemplateResponse(
        request,
        "upload.html",
        build_context(request, errors=[], form_values={}),
    )


@router.post("/drafts/upload", response_class=HTMLResponse)
async def upload_draft(
    request: Request,
    images: list[UploadFile] = File(default_factory=list),
    notes: str = Form(default=""),
    product_name: str = Form(default=""),
    condition: str = Form(default=""),
    accessories: str = Form(default=""),
    hints: str = Form(default=""),
):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    service = DraftUploadService(settings.data_dir)
    analysis_service = HeuristicDraftAnalysisService()
    form_values = {
        "notes": notes,
        "product_name": product_name,
        "condition": condition,
        "accessories": accessories,
        "hints": hints,
    }

    assets = [
        UploadAsset(filename=image.filename, content_type=image.content_type, stream=image.file)
        for image in images
        if image.filename
    ]

    try:
        result = service.create_draft_from_upload(
            files=assets,
            notes=notes,
            user_input={
                "product_name": product_name,
                "condition": condition,
                "accessories": accessories,
                "hints": hints,
            },
        )
        analysis = analysis_service.analyze(result.draft)
        apply_analysis_result(result.draft, analysis)
    except UploadValidationError as exc:
        return templates.TemplateResponse(
            request,
            "upload.html",
            build_context(request, errors=[str(exc)], form_values=form_values),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    finally:
        for image in images:
            await image.close()

    repository.save_draft(result.draft)
    return RedirectResponse(url=f"/drafts/{result.draft.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/drafts/{draft_id}", response_class=HTMLResponse)
def draft_detail(request: Request, draft_id: str):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    marketplace_readiness_errors = collect_marketplace_readiness_errors(
        draft,
        settings,
        include_workflow_status=False,
    )
    marketplace_notes = collect_marketplace_notes(draft)
    ebay_action_disabled = (
        draft.workflow.status is not WorkflowStatus.READY_FOR_MARKETPLACE
        or bool(marketplace_readiness_errors)
    )

    return templates.TemplateResponse(
        request,
        "draft_detail.html",
        build_context(
            request,
            draft=draft,
            review_state=evaluate_review_state(draft),
            missing_core_fields=get_missing_core_fields(draft),
            confidence_notes=get_confidence_notes(draft),
            review_metadata=get_review_metadata(draft),
            marketplace_readiness_errors=marketplace_readiness_errors,
            marketplace_notes=marketplace_notes,
            ebay_action_disabled=ebay_action_disabled,
            marketplace_status_label=("Bereit für eBay-Draft" if not ebay_action_disabled else "Noch nicht bereit"),
            review_status_label=("Review abgeschlossen" if not draft.workflow.needs_review else "Review noch offen"),
            core_fields=CORE_FIELDS,
            optional_fields=OPTIONAL_FIELDS,
        ),
    )


@router.post("/drafts/{draft_id}/review", response_class=HTMLResponse)
async def draft_review_submit(
    request: Request,
    draft_id: str,
    title: str = Form(default=""),
    condition: str = Form(default=""),
    description: str = Form(default=""),
    included_items: str = Form(default=""),
    brand: str = Form(default=""),
    model: str = Form(default=""),
    subtitle: str = Form(default=""),
    category_suggestion: str = Form(default=""),
    hints: str = Form(default=""),
    confirm_fields: list[str] = Form(default_factory=list),
    action: str = Form(default="save"),
):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    update_draft_from_review(
        draft,
        title=title,
        condition=condition,
        description=description,
        included_items=included_items,
        brand=brand,
        model=model,
        subtitle=subtitle,
        category_suggestion=category_suggestion,
        hints=hints,
        confirm_fields=confirm_fields,
        action=action,
    )
    repository.save_draft(draft)
    return RedirectResponse(url=f"/drafts/{draft.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/drafts/{draft_id}/marketplace/ebay", response_class=HTMLResponse)
def draft_create_ebay_offer(draft_id: str):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    service = EbayMarketplaceService(settings=settings, repository=repository)
    service.create_unpublished_offer_for_draft(draft_id)
    return RedirectResponse(url=f"/drafts/{draft_id}", status_code=status.HTTP_303_SEE_OTHER)
