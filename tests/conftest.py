from __future__ import annotations

from pathlib import Path

import pytest

from spo.app import AppState
from spo.config import Settings
from spo.persistence import Database
from spo.sync import JobRunner, ServiceRegistry, SyncEngine
from tests.fakes import FakeSpotifyAdapter, FakeYouTubeMusicAdapter


@pytest.fixture(autouse=True)
def reset_fake_state():
    FakeSpotifyAdapter.STATE = {}
    FakeYouTubeMusicAdapter.STATE = {}
    yield
    FakeSpotifyAdapter.STATE = {}
    FakeYouTubeMusicAdapter.STATE = {}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        bind_host="127.0.0.1",
        bind_port=8899,
        log_level="INFO",
        app_data_dir=tmp_path,
        auto_resume=False,
    )


@pytest.fixture
def app_state(settings: Settings) -> AppState:
    db = Database(settings.db_path)
    db.initialize()
    registry = ServiceRegistry(settings)
    registry.register(FakeSpotifyAdapter.service, FakeSpotifyAdapter)
    registry.register(FakeYouTubeMusicAdapter.service, FakeYouTubeMusicAdapter)
    engine = SyncEngine(db, settings, registry)
    runner = JobRunner(engine, db)
    return AppState(
        settings=settings, db=db, registry=registry, engine=engine, runner=runner
    )
