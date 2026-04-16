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
    assert settings.ebay_payment_policy_id is None

    get_settings.cache_clear()
