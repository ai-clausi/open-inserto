import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Open Inserto"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = True

    project_dir: Path = Path(".")
    data_dir: Path = Path("data")
    database_url: str = "sqlite:///data/open_inserto.db"

    ebay_mode: str = Field(default="sandbox", pattern="^(sandbox|live)$")
    ebay_marketplace_id: str = "EBAY_DE"
    ebay_content_language: str = "de-DE"
    ebay_currency: str = "EUR"
    ebay_client_id: str | None = None
    ebay_client_secret: str | None = None
    ebay_ru_name: str | None = None

    draft_analysis_backend: str = Field(default="auto", pattern="^(heuristic|vision|auto)$")
    vision_provider: str = Field(default="openai", pattern="^(openai)$")
    vision_model: str = "gpt-4.1-mini"
    vision_api_key: str | None = None
    vision_timeout_seconds: float = 30.0
    vision_image_max_side: int = Field(default=1024, ge=256, le=2048)
    vision_image_quality: int = Field(default=72, ge=40, le=95)
    vision_image_detail: str = Field(default="low", pattern="^(low|auto|high)$")
    vision_max_images: int = Field(default=4, ge=1, le=20)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def database_path(self) -> Path:
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            return Path(self.database_url[len(prefix) :])
        return Path(self.database_url)

    @property
    def has_vision_config(self) -> bool:
        return self.vision_provider == "openai" and bool(self.vision_api_key and self.vision_model)

    @property
    def ebay_api_base_url(self) -> str:
        if self.ebay_mode == "live":
            return "https://api.ebay.com"
        return "https://api.sandbox.ebay.com"

    @property
    def ebay_auth_base_url(self) -> str:
        if self.ebay_mode == "live":
            return "https://auth.ebay.com"
        return "https://auth.sandbox.ebay.com"


@lru_cache
def get_settings() -> Settings:
    project_dir = Path(os.getenv("PROJECT_DIR", ".")).resolve()
    env_file = project_dir / ".env"
    settings = Settings(_env_file=env_file if env_file.exists() else None)
    settings.project_dir = settings.project_dir.resolve()
    if not settings.data_dir.is_absolute():
        settings.data_dir = (settings.project_dir / settings.data_dir).resolve()

    database_path = settings.database_path
    if not database_path.is_absolute():
        database_path = (settings.project_dir / database_path).resolve()
        settings.database_url = f"sqlite:///{database_path}"

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
