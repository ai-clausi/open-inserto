from pathlib import Path

from app.core.config import Settings, get_settings


def test_get_settings_reads_env_file_from_project_dir_not_cwd(tmp_path: Path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / ".env").write_text("EBAY_PAYMENT_POLICY_ID=from-cwd\n", encoding="utf-8")

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    monkeypatch.chdir(cwd)
    monkeypatch.setenv("PROJECT_DIR", str(project_dir))
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.project_dir == project_dir.resolve()
    get_settings.cache_clear()


def test_get_settings_reads_draft_analysis_configuration(tmp_path: Path, monkeypatch):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / ".env").write_text(
        "\n".join(
            [
                "DRAFT_ANALYSIS_BACKEND=vision",
                "VISION_PROVIDER=openai",
                "VISION_MODEL=gpt-4.1-mini",
                "VISION_API_KEY=test-key",
                "VISION_TIMEOUT_SECONDS=12.5",
                "VISION_IMAGE_MAX_SIDE=900",
                "VISION_IMAGE_QUALITY=68",
                "VISION_IMAGE_DETAIL=low",
                "VISION_MAX_IMAGES=3",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PROJECT_DIR", str(project_dir))
    for env_var in (
        "DRAFT_ANALYSIS_BACKEND",
        "VISION_PROVIDER",
        "VISION_MODEL",
        "VISION_API_KEY",
        "VISION_TIMEOUT_SECONDS",
        "VISION_IMAGE_MAX_SIDE",
        "VISION_IMAGE_QUALITY",
        "VISION_IMAGE_DETAIL",
        "VISION_MAX_IMAGES",
    ):
        monkeypatch.delenv(env_var, raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.draft_analysis_backend == "vision"
    assert settings.vision_provider == "openai"
    assert settings.vision_model == "gpt-4.1-mini"
    assert settings.vision_api_key == "test-key"
    assert settings.vision_timeout_seconds == 12.5
    assert settings.vision_image_max_side == 900
    assert settings.vision_image_quality == 68
    assert settings.vision_image_detail == "low"
    assert settings.vision_max_images == 3
    assert settings.has_vision_config is True
    get_settings.cache_clear()


def test_settings_selects_sandbox_ebay_credentials():
    settings = Settings(
        _env_file=None,
        ebay_mode="sandbox",
        ebay_sandbox_client_id="sandbox-client",
        ebay_sandbox_client_secret="sandbox-secret",
        ebay_sandbox_ru_name="sandbox-runame",
        ebay_live_client_id="live-client",
        ebay_live_client_secret="live-secret",
        ebay_live_ru_name="live-runame",
    )

    assert settings.ebay_client_id == "sandbox-client"
    assert settings.ebay_client_secret == "sandbox-secret"
    assert settings.ebay_ru_name == "sandbox-runame"
    assert settings.ebay_api_base_url == "https://api.sandbox.ebay.com"
    assert settings.ebay_media_base_url == "https://apim.sandbox.ebay.com"


def test_settings_selects_live_ebay_credentials():
    settings = Settings(
        _env_file=None,
        ebay_mode="live",
        ebay_sandbox_client_id="sandbox-client",
        ebay_sandbox_client_secret="sandbox-secret",
        ebay_sandbox_ru_name="sandbox-runame",
        ebay_live_client_id="live-client",
        ebay_live_client_secret="live-secret",
        ebay_live_ru_name="live-runame",
    )

    assert settings.ebay_client_id == "live-client"
    assert settings.ebay_client_secret == "live-secret"
    assert settings.ebay_ru_name == "live-runame"
    assert settings.ebay_api_base_url == "https://api.ebay.com"
    assert settings.ebay_media_base_url == "https://apim.ebay.com"


def test_settings_keeps_legacy_ebay_credentials_as_fallback():
    settings = Settings(
        _env_file=None,
        ebay_mode="live",
        ebay_client_id="legacy-client",
        ebay_client_secret="legacy-secret",
        ebay_ru_name="legacy-runame",
    )

    assert settings.ebay_client_id == "legacy-client"
    assert settings.ebay_client_secret == "legacy-secret"
    assert settings.ebay_ru_name == "legacy-runame"
