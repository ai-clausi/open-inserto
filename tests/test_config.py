from pathlib import Path

from app.core.config import get_settings


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
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PROJECT_DIR", str(project_dir))
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.draft_analysis_backend == "vision"
    assert settings.vision_provider == "openai"
    assert settings.vision_model == "gpt-4.1-mini"
    assert settings.vision_api_key == "test-key"
    assert settings.vision_timeout_seconds == 12.5
    assert settings.has_vision_config is True
    get_settings.cache_clear()
