from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "spo"
APP_AUTHOR = "spo"


@dataclass(slots=True)
class Settings:
    bind_host: str
    bind_port: int
    log_level: str
    app_data_dir: Path
    auto_resume: bool = True

    @property
    def db_path(self) -> Path:
        return self.app_data_dir / "state.db"

    @property
    def log_path(self) -> Path:
        return self.app_data_dir / "app.log"

    @property
    def settings_path(self) -> Path:
        return self.app_data_dir / "settings.toml"


def _default_app_data_dir() -> Path:
    return Path(
        os.getenv("SPO_DATA_DIR", user_data_dir(APP_NAME, APP_AUTHOR, roaming=True))
    )


def _coerce_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def load_settings() -> Settings:
    app_data_dir = _default_app_data_dir()
    config_data: dict[str, object] = {}
    settings_path = app_data_dir / "settings.toml"

    if settings_path.exists():
        with settings_path.open("rb") as handle:
            config_data = tomllib.load(handle)

    app_data_dir = Path(
        str(config_data.get("app_data_dir", os.getenv("SPO_DATA_DIR", app_data_dir)))
    )
    app_data_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        bind_host=str(config_data.get("bind_host", "127.0.0.1")),
        bind_port=_coerce_int(config_data.get("bind_port", 8899), 8899),
        log_level=str(config_data.get("log_level", "INFO")).upper(),
        app_data_dir=app_data_dir,
        auto_resume=bool(config_data.get("auto_resume", True)),
    )
