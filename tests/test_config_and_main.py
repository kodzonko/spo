# ruff: noqa: D103, S101
# Pytest bare asserts are idiomatic here, and per-test docstrings add little value.
"""Tests for config loading and CLI defaults."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from spo import main as main_module
from spo.config import APP_DATA_DIRNAME, load_settings

HOST_ALL_INTERFACES = "0.0.0.0"  # noqa: S104 - explicit bind target used in this regression test.
DEFAULT_HOST = "127.0.0.1"
SETTINGS_PORT = 9011
WEB_PORT = 9009
DEFAULT_PORT = 8899


def _app_data_dir_for(repo_root: Path) -> Path:
    return repo_root / APP_DATA_DIRNAME


def test_load_settings_reads_settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_dir = _app_data_dir_for(tmp_path)
    settings_dir.mkdir()
    (settings_dir / "settings.toml").write_text(
        f'bind_host = "{HOST_ALL_INTERFACES}"\nbind_port = {SETTINGS_PORT}\nlog_level = "debug"\nauto_resume = false\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("spo.config._repo_root", lambda: tmp_path)

    settings = load_settings()

    assert settings.bind_host == HOST_ALL_INTERFACES
    assert settings.bind_port == SETTINGS_PORT
    assert settings.log_level == "DEBUG"
    assert settings.auto_resume is False
    assert settings.db_path == settings_dir / "state.db"
    assert settings.log_path == settings_dir / "app.log"
    assert settings.settings_path == settings_dir / "settings.toml"


def test_load_settings_ignores_app_data_dir_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_dir = _app_data_dir_for(tmp_path)
    settings_dir.mkdir()
    (settings_dir / "settings.toml").write_text(
        f'app_data_dir = "/tmp/elsewhere"\nbind_port = {SETTINGS_PORT}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("spo.config._repo_root", lambda: tmp_path)

    settings = load_settings()

    assert settings.app_data_dir == settings_dir
    assert settings.db_path == settings_dir / "state.db"
    assert settings.bind_port == SETTINGS_PORT


def test_main_web_invokes_uvicorn_with_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_dir = _app_data_dir_for(tmp_path)
    monkeypatch.setattr("spo.config._repo_root", lambda: tmp_path)

    captured: dict[str, object] = {}

    def fake_run(app: object, host: str, port: int) -> None:
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(main_module.uvicorn, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["spo", "web", "--host", HOST_ALL_INTERFACES, "--port", str(WEB_PORT)])

    main_module.main()

    assert captured["host"] == HOST_ALL_INTERFACES
    assert captured["port"] == WEB_PORT
    assert settings_dir.exists()


def test_main_defaults_to_web_without_subcommand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_dir = _app_data_dir_for(tmp_path)
    monkeypatch.setattr("spo.config._repo_root", lambda: tmp_path)

    captured: dict[str, object] = {}

    def fake_run(app: object, host: str, port: int) -> None:
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(main_module.uvicorn, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["spo"])

    main_module.main()

    assert captured["host"] == DEFAULT_HOST
    assert captured["port"] == DEFAULT_PORT
    assert settings_dir.exists()
