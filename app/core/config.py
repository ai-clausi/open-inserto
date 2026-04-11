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
    ebay_client_id: str | None = None
    ebay_client_secret: str | None = None
    ebay_ru_name: str | None = None
    ebay_access_token: str | None = None
    ebay_refresh_token: str | None = None

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


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
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
