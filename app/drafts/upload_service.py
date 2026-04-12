from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from app.drafts.identity import derive_sku, generate_draft_id
from app.drafts.models import Draft, SourceImage

register_heif_opener()

ALLOWED_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tif",
}
ALLOWED_EXTENSIONS = set(ALLOWED_MIME_TYPES.values())
MAX_UPLOAD_IMAGES = 20
MIN_LONGEST_SIDE = 500
NORMALIZED_MIME_TYPE = "image/jpeg"
NORMALIZED_SUFFIX = ".jpg"


class UploadValidationError(ValueError):
    pass


@dataclass(slots=True)
class UploadAsset:
    filename: str
    content_type: str | None
    stream: BinaryIO


@dataclass(slots=True)
class UploadResult:
    draft: Draft
    original_paths: list[str]


class DraftUploadService:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.drafts_dir = data_dir / "drafts"
        self.drafts_dir.mkdir(parents=True, exist_ok=True)

    def create_draft_from_upload(
        self,
        *,
        files: list[UploadAsset],
        notes: str = "",
        user_input: dict[str, str] | None = None,
    ) -> UploadResult:
        normalized_user_input = {key: value.strip() for key, value in (user_input or {}).items() if value.strip()}
        validated_files = self._validate_files(files)

        draft_id = generate_draft_id()
        draft_dir = self.drafts_dir / draft_id
        originals_dir = draft_dir / "images" / "originals"
        normalized_dir = draft_dir / "images" / "normalized"
        originals_dir.mkdir(parents=True, exist_ok=True)
        normalized_dir.mkdir(parents=True, exist_ok=True)

        source_images: list[SourceImage] = []
        original_paths: list[str] = []

        for index, asset in enumerate(validated_files, start=1):
            image, original_bytes = self._load_image(asset)
            normalized_image = ImageOps.exif_transpose(image)
            if max(normalized_image.size) < MIN_LONGEST_SIDE:
                msg = (
                    f"{asset.filename or f'Bild {index}'} ist zu klein. "
                    f"Die längste Seite muss mindestens {MIN_LONGEST_SIDE}px haben."
                )
                raise UploadValidationError(msg)

            original_suffix = self._detect_suffix(asset)
            original_path = originals_dir / f"{index:02d}-original{original_suffix}"
            original_path.write_bytes(original_bytes)
            original_paths.append(str(original_path.relative_to(self.data_dir.parent)))

            normalized_path = normalized_dir / f"{index:02d}-normalized{NORMALIZED_SUFFIX}"
            rgb_image = normalized_image.convert("RGB")
            rgb_image.save(normalized_path, format="JPEG", quality=92, optimize=True)

            source_images.append(
                SourceImage(
                    id=f"img_{uuid4().hex[:8]}",
                    originalFilename=asset.filename or f"upload-{index}{original_suffix}",
                    storagePath=str(normalized_path.relative_to(self.data_dir.parent)),
                    mimeType=NORMALIZED_MIME_TYPE,
                    order=index,
                    kind="normalized",
                )
            )

        draft = Draft(
            id=draft_id,
            sku=derive_sku(draft_id),
            source={
                "images": source_images,
                "notes": notes.strip(),
                "userInput": normalized_user_input,
            },
        )
        return UploadResult(draft=draft, original_paths=original_paths)

    def _validate_files(self, files: list[UploadAsset]) -> list[UploadAsset]:
        non_empty = [file for file in files if (file.filename or "").strip()]
        if not non_empty:
            raise UploadValidationError("Bitte mindestens ein Bild auswählen.")
        if len(non_empty) > MAX_UPLOAD_IMAGES:
            raise UploadValidationError(f"Bitte maximal {MAX_UPLOAD_IMAGES} Bilder hochladen.")
        return non_empty

    def _load_image(self, asset: UploadAsset) -> tuple[Image.Image, bytes]:
        content = asset.stream.read()
        if not content:
            raise UploadValidationError(f"{asset.filename or 'Eine Datei'} ist leer.")

        suffix = self._detect_suffix(asset)
        if suffix not in ALLOWED_EXTENSIONS:
            raise UploadValidationError(
                f"{asset.filename or 'Die Datei'} hat einen nicht unterstützten Bildtyp."
            )

        try:
            image = Image.open(BytesIO(content))
            image.load()
        except UnidentifiedImageError as exc:
            raise UploadValidationError(
                f"{asset.filename or 'Die Datei'} konnte nicht als Bild gelesen werden."
            ) from exc

        detected_mime = Image.MIME.get(image.format or "")
        allowed_by_header = (asset.content_type or "").lower() in ALLOWED_MIME_TYPES
        allowed_by_decoder = (detected_mime or "").lower() in ALLOWED_MIME_TYPES
        if not (allowed_by_header or allowed_by_decoder):
            raise UploadValidationError(
                f"{asset.filename or 'Die Datei'} ist kein unterstütztes Bildformat."
            )

        return image, content

    def _detect_suffix(self, asset: UploadAsset) -> str:
        filename = (asset.filename or "").lower()
        suffix = Path(filename).suffix
        if suffix in ALLOWED_EXTENSIONS:
            return ".jpg" if suffix == ".jpeg" else suffix

        content_type = (asset.content_type or "").lower()
        detected = ALLOWED_MIME_TYPES.get(content_type)
        if detected:
            return detected

        return suffix
