from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
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
from app.marketplaces.ebay.auth import EbayAuthStore, build_auth_connect_url
from app.marketplaces.ebay.client import EbayAuthError, EbayClient
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
    auth_store = EbayAuthStore(settings.database_path)
    token_data = auth_store.get_tokens()
    ebay_auth_connected = bool(
        token_data.refresh_token or token_data.access_token or settings.ebay_refresh_token or settings.ebay_access_token
    )
    context = {
        "request": request,
        "app_name": settings.app_name,
        "ebay_mode": settings.ebay_mode,
        "database_url": settings.database_url,
        "extra_fields": EXTRA_FIELDS,
        "ebay_auth_connected": ebay_auth_connected,
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
    auth_store = EbayAuthStore(settings.database_path)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    auth_tokens = auth_store.get_tokens()
    ebay_auth_connected = bool(auth_tokens.refresh_token or auth_tokens.access_token or settings.ebay_refresh_token or settings.ebay_access_token)
    marketplace_readiness_errors = collect_marketplace_readiness_errors(
        draft,
        settings,
        include_workflow_status=False,
        auth_connected=ebay_auth_connected,
    )
    marketplace_notes = collect_marketplace_notes(draft)
    ebay_action_disabled = (
        draft.workflow.status is not WorkflowStatus.READY_FOR_MARKETPLACE
        or bool(marketplace_readiness_errors)
    )

    review_state = evaluate_review_state(draft)
    review_status_label = "Review abgeschlossen" if not draft.workflow.needs_review else "Review noch offen"
    if not marketplace_readiness_errors:
        marketplace_status_label = "Bereit für eBay-Draft"
    elif any("ist nicht konfiguriert" in item for item in marketplace_readiness_errors):
        marketplace_status_label = "Blockiert durch Konfiguration"
    else:
        marketplace_status_label = "Noch Angaben prüfen"

    return templates.TemplateResponse(
        request,
        "draft_detail.html",
        build_context(
            request,
            draft=draft,
            review_state=review_state,
            missing_core_fields=get_missing_core_fields(draft),
            confidence_notes=get_confidence_notes(draft),
            review_metadata=get_review_metadata(draft),
            marketplace_readiness_errors=marketplace_readiness_errors,
            marketplace_notes=marketplace_notes,
            ebay_action_disabled=ebay_action_disabled,
            marketplace_status_label=marketplace_status_label,
            review_status_label=review_status_label,
            review_state_label=(
                "Kernangaben vollständig" if review_state == "ready" else "Kernangaben noch prüfen"
            ),
            show_technical_workflow_hint=(review_state != "ready" or bool(marketplace_readiness_errors)),
            core_fields=CORE_FIELDS,
            optional_fields=OPTIONAL_FIELDS,
            ebay_auth_connected=ebay_auth_connected,
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

    auth_store = EbayAuthStore(settings.database_path)
    service = EbayMarketplaceService(
        settings=settings,
        repository=repository,
        client=EbayClient(settings, auth_store=auth_store),
    )
    service.create_unpublished_offer_for_draft(draft_id)
    return RedirectResponse(url=f"/drafts/{draft_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/integrations/ebay/connect")
def ebay_connect():
    settings = get_settings()
    if not settings.ebay_client_id or not settings.ebay_ru_name:
        raise HTTPException(status_code=400, detail="eBay OAuth ist nicht vollständig konfiguriert")

    auth_store = EbayAuthStore(settings.database_path)
    state = auth_store.issue_state()
    return RedirectResponse(url=build_auth_connect_url(settings, state), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/integrations/ebay/callback", response_class=HTMLResponse)
def ebay_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    settings = get_settings()
    auth_store = EbayAuthStore(settings.database_path)

    if error:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"eBay-Autorisierung fehlgeschlagen: {error}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    expected_state = auth_store.get_pending_state()
    if not state or state != expected_state:
        raise HTTPException(status_code=400, detail="Ungültiger eBay OAuth-Status")
    if not code:
        raise HTTPException(status_code=400, detail="eBay OAuth-Code fehlt")

    client = EbayClient(settings, auth_store=auth_store)
    try:
        client.exchange_authorization_code(code)
    except EbayAuthError as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"eBay-Verbindung konnte nicht hergestellt werden: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    finally:
        client.close()
        auth_store.clear_state()

    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(request, ebay_connect_success="eBay wurde erfolgreich verbunden. Die Tokens werden jetzt in der App gespeichert."),
    )
