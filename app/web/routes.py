from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.drafts.repository import DraftRepository
from app.drafts.upload_service import DraftUploadService, UploadAsset, UploadValidationError

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

    return templates.TemplateResponse(
        request,
        "draft_detail.html",
        build_context(request, draft=draft),
    )
