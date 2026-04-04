from __future__ import annotations

from spo import main as main_module
from spo.config import load_settings


def test_load_settings_reads_settings_file(tmp_path, monkeypatch):
    settings_dir = tmp_path / "spo-data"
    settings_dir.mkdir()
    (settings_dir / "settings.toml").write_text(
        'bind_host = "0.0.0.0"\n'
        "bind_port = 9011\n"
        'log_level = "debug"\n'
        "auto_resume = false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SPO_DATA_DIR", str(settings_dir))

    settings = load_settings()

    assert settings.bind_host == "0.0.0.0"
    assert settings.bind_port == 9011
    assert settings.log_level == "DEBUG"
    assert settings.auto_resume is False
    assert settings.db_path == settings_dir / "state.db"
    assert settings.log_path == settings_dir / "app.log"
    assert settings.settings_path == settings_dir / "settings.toml"


def test_main_web_invokes_uvicorn_with_overrides(tmp_path, monkeypatch):
    settings_dir = tmp_path / "spo-data"
    monkeypatch.setenv("SPO_DATA_DIR", str(settings_dir))

    captured: dict[str, object] = {}

    def fake_run(app, host: str, port: int) -> None:
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(main_module.uvicorn, "run", fake_run)
    monkeypatch.setattr(
        "sys.argv", ["spo", "web", "--host", "0.0.0.0", "--port", "9009"]
    )

    main_module.main()

    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9009
    assert settings_dir.exists()
