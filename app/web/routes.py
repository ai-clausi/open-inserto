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
from app.marketplaces.ebay.auth import EbayAuthStore, build_auth_connect_url, has_usable_auth_tokens
from app.marketplaces.ebay.client import EbayApiError, EbayAuthError, EbayClient, EbayValidationError, normalize_search_text
from app.marketplaces.ebay.configuration import EbayConfigStore
from app.marketplaces.ebay.validation import collect_marketplace_notes, collect_marketplace_readiness_errors

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


EXTRA_FIELDS = [
    ("product_name", "Produktname"),
    ("condition", "Zustand"),
    ("accessories", "Zubehör"),
    ("hints", "Hinweise"),
]


STATUS_LABELS = {
    WorkflowStatus.DRAFT: "Neu",
    WorkflowStatus.CLASSIFIED: "Klassifiziert",
    WorkflowStatus.NEEDS_ATTENTION: "Braucht Aufmerksamkeit",
    WorkflowStatus.READY_FOR_REVIEW: "Bereit fürs Review",
    WorkflowStatus.READY_FOR_MARKETPLACE: "Bereit für eBay",
    WorkflowStatus.OFFER_CREATED: "eBay-Draft erstellt",
    WorkflowStatus.PUBLISHED: "Veröffentlicht",
    WorkflowStatus.BLOCKED: "Blockiert",
    WorkflowStatus.ERROR: "Fehler",
}


def build_context(request: Request, **extra):
    settings = get_settings()
    auth_store = EbayAuthStore(settings.database_path)
    config_store = EbayConfigStore(settings.database_path)
    token_data = auth_store.get_tokens()
    ebay_auth_connected = has_usable_auth_tokens(token_data)
    effective_config = config_store.get_effective_configuration()
    discovered_resources = config_store.get_discovered_resources()
    context = {
        "request": request,
        "app_name": settings.app_name,
        "ebay_mode": settings.ebay_mode,
        "database_url": settings.database_url,
        "extra_fields": EXTRA_FIELDS,
        "ebay_auth_connected": ebay_auth_connected,
        "ebay_effective_config": effective_config,
        "ebay_discovered_resources": discovered_resources,
        "ebay_policy_management_opted_in": extra.get("ebay_policy_management_opted_in"),
    }
    context.update(extra)
    return context


def build_draft_result_summary(
    *,
    draft,
    review_state: str,
    ebay_auth_connected: bool,
    marketplace_readiness_errors: list[str],
) -> dict[str, object]:
    ebay_error = str(draft.marketplace.ebay.offer_data.get("lastError") or "").strip()

    if draft.marketplace.ebay.offer_id:
        return {
            "headline": "eBay-Draft erfolgreich erstellt",
            "body": "Der Draft wurde an eBay übertragen. Wenn du magst, kannst du jetzt nur noch kurz die technischen Details prüfen.",
            "tone": "success",
            "primary_action_label": "Weiter prüfen",
            "primary_action_target": "technical-details",
        }

    if not ebay_auth_connected:
        return {
            "headline": "eBay muss neu verbunden werden",
            "body": "Die Verbindung zu eBay fehlt oder ist nicht mehr gültig. Danach kannst du den Draft direkt erneut senden.",
            "tone": "warning",
            "primary_action_label": "eBay erneut verbinden",
            "primary_action_target": "ebay-connect",
        }

    if marketplace_readiness_errors:
        return {
            "headline": "Es fehlen noch Angaben",
            "body": "Bevor der eBay-Schritt laufen kann, sollte der Draft noch an den markierten Punkten vervollständigt werden.",
            "tone": "warning",
            "primary_action_label": "Angaben ergänzen",
            "primary_action_target": "review-form",
        }

    if ebay_error:
        return {
            "headline": "eBay hat den letzten Versuch abgelehnt",
            "body": "Der lokale Draft ist erhalten geblieben. Du kannst den Schritt nach der kurzen Prüfung direkt erneut ausführen.",
            "tone": "error",
            "primary_action_label": "Erneut senden",
            "primary_action_target": "ebay-send",
        }

    if review_state != "ready":
        return {
            "headline": "Bitte kurz prüfen",
            "body": "Die Kernangaben sind noch nicht vollständig bestätigt. Danach kann der Marketplace-Schritt folgen.",
            "tone": "info",
            "primary_action_label": "Review öffnen",
            "primary_action_target": "review-form",
        }

    return {
        "headline": "Bereit für den nächsten Schritt",
        "body": "Der Draft wirkt vollständig. Du kannst jetzt mit einem Klick den eBay-Draft anstoßen.",
        "tone": "info",
        "primary_action_label": "eBay-Draft senden",
        "primary_action_target": "ebay-send",
    }


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


@router.get("/drafts", response_class=HTMLResponse)
def draft_list(request: Request):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    drafts = sorted(
        repository.list_drafts(),
        key=lambda draft: draft.workflow.last_updated_at,
        reverse=True,
    )
    draft_items = [
        {
            "id": draft.id,
            "sku": draft.sku,
            "status": draft.workflow.status,
            "status_label": STATUS_LABELS.get(draft.workflow.status, draft.workflow.status.value),
            "last_updated_at": draft.workflow.last_updated_at.strftime("%d.%m.%Y, %H:%M Uhr"),
            "created_at": draft.workflow.created_at.strftime("%d.%m.%Y, %H:%M Uhr"),
            "detail_url": f"/drafts/{draft.id}",
            "title": draft.listing.title.strip() or f"SKU {draft.sku}",
            "subtitle": draft.listing.subtitle.strip() or draft.listing.condition.strip() or "Entwurf bereit zum Weiterbearbeiten",
            "image_url": f"/{draft.source.images[0].storage_path}" if draft.source.images else None,
            "image_alt": draft.source.images[0].original_filename if draft.source.images else "Kein Vorschaubild vorhanden",
        }
        for draft in drafts
    ]
    return templates.TemplateResponse(
        request,
        "draft_list.html",
        build_context(request, drafts=draft_items),
    )


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
    config_store = EbayConfigStore(settings.database_path)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    auth_tokens = auth_store.get_tokens()
    ebay_auth_connected = has_usable_auth_tokens(auth_tokens)
    effective_config = config_store.get_effective_configuration()
    marketplace_readiness_errors = collect_marketplace_readiness_errors(
        draft,
        effective_config,
        include_workflow_status=False,
        auth_connected=ebay_auth_connected,
    )
    marketplace_notes = collect_marketplace_notes(draft)
    ebay_action_disabled = (
        draft.workflow.status not in {WorkflowStatus.READY_FOR_MARKETPLACE, WorkflowStatus.ERROR}
        or bool(marketplace_readiness_errors)
    )

    review_state = evaluate_review_state(draft)
    review_status_label = "Review abgeschlossen" if not draft.workflow.needs_review else "Review noch offen"
    if draft.marketplace.ebay.offer_id:
        marketplace_status_label = "Erfolgreich erstellt"
    elif not marketplace_readiness_errors and draft.marketplace.ebay.offer_data.get("lastError"):
        marketplace_status_label = "Retry möglich"
    elif not marketplace_readiness_errors:
        marketplace_status_label = "Bereit für eBay-Draft"
    elif any("ist nicht konfiguriert" in item for item in marketplace_readiness_errors):
        marketplace_status_label = "Blockiert durch Konfiguration"
    else:
        marketplace_status_label = "Noch Angaben prüfen"
    result_summary = build_draft_result_summary(
        draft=draft,
        review_state=review_state,
        ebay_auth_connected=ebay_auth_connected,
        marketplace_readiness_errors=marketplace_readiness_errors,
    )

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
            ebay_effective_config=effective_config,
            marketplace_status_label=marketplace_status_label,
            review_status_label=review_status_label,
            review_state_label=(
                "Kernangaben vollständig" if review_state == "ready" else "Kernangaben noch prüfen"
            ),
            show_technical_workflow_hint=(review_state != "ready" or bool(marketplace_readiness_errors)),
            core_fields=CORE_FIELDS,
            optional_fields=OPTIONAL_FIELDS,
            ebay_auth_connected=ebay_auth_connected,
            result_summary=result_summary,
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
        config_store=EbayConfigStore(settings.database_path),
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
    config_store = EbayConfigStore(settings.database_path)

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
    message = "eBay wurde erfolgreich verbunden. Die Tokens werden jetzt in der App gespeichert."
    discovery_notice = None
    try:
        client.exchange_authorization_code(code)
        try:
            resources = client.get_account_resources(client.get_access_token())
            config_store.save_discovered_resources(resources)
            effective_config = config_store.auto_select_defaults(resources)
            auto_selected = []
            if effective_config.payment_policy_id:
                auto_selected.append("Payment Policy")
            if effective_config.fulfillment_policy_id:
                auto_selected.append("Fulfillment Policy")
            if effective_config.return_policy_id:
                auto_selected.append("Return Policy")
            if effective_config.merchant_location_key:
                auto_selected.append("Merchant Location")
            if auto_selected:
                message += f" Erkannte Defaults: {', '.join(auto_selected)}."
        except (EbayValidationError, EbayApiError) as exc:
            discovery_notice = f"Die Account-Ressourcen konnten nach dem Login nicht automatisch geladen werden: {exc}"
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
        build_context(request, ebay_connect_success=message, ebay_connect_error=discovery_notice),
    )


@router.post("/integrations/ebay/defaults")
async def ebay_save_defaults(
    payment_policy_id: str = Form(default=""),
    fulfillment_policy_id: str = Form(default=""),
    return_policy_id: str = Form(default=""),
    merchant_location_key: str = Form(default=""),
):
    settings = get_settings()
    config_store = EbayConfigStore(settings.database_path)
    config_store.save_selected_configuration(
        payment_policy_id=payment_policy_id.strip() or None,
        fulfillment_policy_id=fulfillment_policy_id.strip() or None,
        return_policy_id=return_policy_id.strip() or None,
        merchant_location_key=merchant_location_key.strip() or None,
    )
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/integrations/ebay/discover")
def ebay_discover_defaults(request: Request):
    settings = get_settings()
    auth_store = EbayAuthStore(settings.database_path)
    config_store = EbayConfigStore(settings.database_path)
    token_data = auth_store.get_tokens()
    if not has_usable_auth_tokens(token_data):
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error="Bitte zuerst mit eBay verbinden."),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    client = EbayClient(settings, auth_store=auth_store)
    try:
        access_token = client.get_access_token()
        opted_in_programs = client.get_opted_in_programs(access_token)
        policy_management_opted_in = "SELLING_POLICY_MANAGEMENT" in opted_in_programs
        if not policy_management_opted_in:
            return templates.TemplateResponse(
                request,
                "index.html",
                build_context(
                    request,
                    ebay_policy_management_opted_in=False,
                    ebay_connect_error=(
                        "Der verbundene eBay-Account ist noch nicht für Business Policies freigeschaltet. "
                        "Bitte 'Selling Policy Management aktivieren' ausführen und danach die Ressourcen erneut laden."
                    ),
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        resources = client.get_account_resources(access_token)
        config_store.save_discovered_resources(resources)
        effective_config = config_store.auto_select_defaults(resources)
    except EbayAuthError as exc:
        auth_store.clear_tokens()
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"eBay-Verbindung ist nicht mehr gültig: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except (EbayValidationError, EbayApiError) as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"Die Account-Ressourcen konnten nicht geladen werden: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    finally:
        client.close()

    found_counts = {
        "Payment Policies": len(resources.payment_policies),
        "Fulfillment Policies": len(resources.fulfillment_policies),
        "Return Policies": len(resources.return_policies),
        "Merchant Locations": len(resources.merchant_locations),
    }
    summary = ", ".join(f"{label}: {count}" for label, count in found_counts.items())

    auto_selected = []
    if effective_config.payment_policy_id:
        auto_selected.append("Payment Policy")
    if effective_config.fulfillment_policy_id:
        auto_selected.append("Fulfillment Policy")
    if effective_config.return_policy_id:
        auto_selected.append("Return Policy")
    if effective_config.merchant_location_key:
        auto_selected.append("Merchant Location")

    message = f"eBay-Account-Ressourcen aktualisiert. Gefunden: {summary}."
    if auto_selected:
        message += f" Automatisch gesetzt: {', '.join(auto_selected)}."

    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(request, ebay_connect_success=message, ebay_policy_management_opted_in=True),
    )


@router.post("/integrations/ebay/programs/selling-policy-management/opt-in")
def ebay_opt_in_selling_policy_management(request: Request):
    settings = get_settings()
    auth_store = EbayAuthStore(settings.database_path)
    token_data = auth_store.get_tokens()
    if not has_usable_auth_tokens(token_data):
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error="Bitte zuerst mit eBay verbinden."),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    client = EbayClient(settings, auth_store=auth_store)
    try:
        access_token = client.get_access_token()
        client.opt_in_to_program(access_token, "SELLING_POLICY_MANAGEMENT")
    except EbayAuthError as exc:
        auth_store.clear_tokens()
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"eBay-Verbindung ist nicht mehr gültig: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except (EbayValidationError, EbayApiError) as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"SELLING_POLICY_MANAGEMENT konnte nicht aktiviert werden: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    finally:
        client.close()

    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(
            request,
            ebay_connect_success=(
                "SELLING_POLICY_MANAGEMENT wurde bei eBay angefordert. "
                "Die Aktivierung kann laut eBay bis zu 24 Stunden dauern. Danach bitte die Account-Ressourcen erneut laden."
            ),
            ebay_policy_management_opted_in=False,
        ),
    )


@router.post("/integrations/ebay/locations/create-default")
def ebay_create_default_location(request: Request):
    settings = get_settings()
    auth_store = EbayAuthStore(settings.database_path)
    config_store = EbayConfigStore(settings.database_path)
    token_data = auth_store.get_tokens()
    if not has_usable_auth_tokens(token_data):
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error="Bitte zuerst mit eBay verbinden."),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    client = EbayClient(settings, auth_store=auth_store)
    merchant_location_key = "open-inserto-default"
    payload = {
        "name": "Open Inserto Default",
        "phone": "+49 0000000000",
        "location": {
            "address": {
                "postalCode": "85049",
                "country": "DE",
            }
        },
        "locationTypes": ["WAREHOUSE"],
        "merchantLocationStatus": "ENABLED",
    }
    try:
        access_token = client.get_access_token()
        try:
            client.create_inventory_location(
                access_token,
                merchant_location_key=merchant_location_key,
                payload=payload,
            )
            success_message = "Standard-Merchant-Location wurde angelegt."
        except EbayValidationError as exc:
            if "already exists" in str(exc).lower():
                success_message = "Standard-Merchant-Location existiert bereits."
            else:
                raise

        discovery_notice = None
        try:
            resources = client.get_account_resources(access_token)
            config_store.save_discovered_resources(resources)
            effective_config = config_store.auto_select_defaults(resources)
            if not effective_config.merchant_location_key:
                config_store.save_selected_configuration(merchant_location_key=merchant_location_key)
            success_message += " Account-Ressourcen wurden anschließend neu geladen."
        except (EbayValidationError, EbayApiError) as exc:
            discovery_notice = (
                "Die Location wurde angelegt, aber die Account-Ressourcen konnten danach noch nicht geladen werden: "
                f"{exc}"
            )
    except EbayAuthError as exc:
        auth_store.clear_tokens()
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"eBay-Verbindung ist nicht mehr gültig: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except (EbayValidationError, EbayApiError) as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"Merchant Location konnte nicht angelegt werden: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    finally:
        client.close()

    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(
            request,
            ebay_connect_success=success_message,
            ebay_connect_error=discovery_notice,
        ),
    )


@router.post("/integrations/ebay/policies/create-defaults")
def ebay_create_default_policies(request: Request):
    settings = get_settings()
    auth_store = EbayAuthStore(settings.database_path)
    config_store = EbayConfigStore(settings.database_path)
    token_data = auth_store.get_tokens()
    if not has_usable_auth_tokens(token_data):
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error="Bitte zuerst mit eBay verbinden."),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    client = EbayClient(settings, auth_store=auth_store)
    try:
        access_token = client.get_access_token()
        shipping_services = client.get_shipping_services(access_token)
        dhl_paket = _resolve_shipping_service_code(
            shipping_services,
            preferred_codes=["DE_DHLPaket"],
            search_terms=["dhl", "paket"],
        )
        dhl_paeckchen = _resolve_shipping_service_code(
            shipping_services,
            preferred_codes=["DE_DHLPackchen", "DE_DHLPaeckchen"],
            search_terms=["dhl", "packchen"],
        )
        if not dhl_paket or not dhl_paeckchen:
            available = ", ".join(
                sorted(
                    {
                        str(item.get("description") or item.get("shippingServiceCode") or item.get("shippingService") or "").strip()
                        for item in shipping_services
                        if isinstance(item, dict)
                    }
                )[:10]
            )
            raise EbayValidationError(
                "Die benötigten DHL-Versandservices konnten für EBAY_DE nicht automatisch aufgelöst werden."
                + (f" Verfügbare Beispiele: {available}" if available else "")
            )

        payment_payload = {
            "name": "Open Inserto - Sofortzahlung",
            "marketplaceId": settings.ebay_marketplace_id,
            "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
            "immediatePay": True,
        }
        return_payload = {
            "name": "Open Inserto - Keine Rücknahme",
            "marketplaceId": settings.ebay_marketplace_id,
            "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
            "returnsAccepted": False,
            "description": "Privatverkauf ohne Rücknahme und Gewährleistung.",
        }
        fulfillment_payload = {
            "name": "Open Inserto - DHL Standard",
            "marketplaceId": settings.ebay_marketplace_id,
            "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
            "handlingTime": {"value": 3, "unit": "DAY"},
            "shippingOptions": [
                {
                    "costType": "FLAT_RATE",
                    "optionType": "DOMESTIC",
                    "shippingServices": [
                        {
                            "shippingCarrierCode": "DHL",
                            "shippingServiceCode": dhl_paket,
                            "shippingCost": {"value": "6.19", "currency": settings.ebay_currency},
                        },
                        {
                            "shippingCarrierCode": "DHL",
                            "shippingServiceCode": dhl_paeckchen,
                            "shippingCost": {"value": "5.19", "currency": settings.ebay_currency},
                        },
                    ],
                }
            ],
        }

        created_labels: list[str] = []
        try:
            client.create_payment_policy(access_token, payment_payload)
            created_labels.append("Payment Policy")
        except EbayValidationError as exc:
            if not _is_duplicate_policy_error(exc):
                raise
        try:
            client.create_return_policy(access_token, return_payload)
            created_labels.append("Return Policy")
        except EbayValidationError as exc:
            if not _is_duplicate_policy_error(exc):
                raise
        try:
            client.create_fulfillment_policy(access_token, fulfillment_payload)
            created_labels.append("Fulfillment Policy")
        except EbayValidationError as exc:
            if not _is_duplicate_policy_error(exc):
                raise

        resources = client.get_account_resources(access_token)
        config_store.save_discovered_resources(resources)
        effective_config = config_store.auto_select_defaults(resources)
        config_store.save_selected_configuration(
            payment_policy_id=_find_resource_id_by_name(resources.payment_policies, payment_payload["name"]) or effective_config.payment_policy_id,
            fulfillment_policy_id=_find_resource_id_by_name(resources.fulfillment_policies, fulfillment_payload["name"]) or effective_config.fulfillment_policy_id,
            return_policy_id=_find_resource_id_by_name(resources.return_policies, return_payload["name"]) or effective_config.return_policy_id,
        )
        effective_config = config_store.get_effective_configuration()
    except EbayAuthError as exc:
        auth_store.clear_tokens()
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"eBay-Verbindung ist nicht mehr gültig: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except (EbayValidationError, EbayApiError) as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"Standard-Business-Policies konnten nicht angelegt werden: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    finally:
        client.close()

    selected = []
    if effective_config.payment_policy_id:
        selected.append("Payment Policy")
    if effective_config.fulfillment_policy_id:
        selected.append("Fulfillment Policy")
    if effective_config.return_policy_id:
        selected.append("Return Policy")
    message = "Standard-Business-Policies wurden angelegt oder waren bereits vorhanden."
    if created_labels:
        message += f" Neu angelegt: {', '.join(created_labels)}."
    if selected:
        message += f" Automatisch gesetzt: {', '.join(selected)}."

    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(request, ebay_connect_success=message),
    )


def _find_shipping_service_code(services: list[dict[str, object]], search_terms: list[str]) -> str | None:
    normalized_terms = [normalize_search_text(term) for term in search_terms]
    for item in services:
        description = normalize_search_text(str(item.get("description") or ""))
        if all(term in description for term in normalized_terms):
            return str(item.get("shippingServiceCode") or item.get("shippingService") or "").strip() or None
    return None


def _resolve_shipping_service_code(
    services: list[dict[str, object]],
    *,
    preferred_codes: list[str],
    search_terms: list[str],
) -> str | None:
    available_codes = {
        str(item.get("shippingServiceCode") or item.get("shippingService") or "").strip()
        for item in services
        if isinstance(item, dict)
    }
    for code in preferred_codes:
        if code in available_codes:
            return code
    return _find_shipping_service_code(services, search_terms)


def _is_duplicate_policy_error(exc: EbayValidationError) -> bool:
    message = str(exc).lower()
    return (
        "duplicate policy" in message
        or "already exists" in message
        or "doppelt vorhanden" in message
        or "20400" in message
    )


def _find_resource_id_by_name(resources: list[dict[str, str]], expected_name: str) -> str | None:
    for item in resources:
        if item.get("name") == expected_name:
            value = item.get("id")
            if value:
                return value
    return None
