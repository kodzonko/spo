"""Shared pytest fixtures for spo tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from spo.app import AppState
from spo.config import Settings
from spo.persistence import Database
from spo.sync import JobRunner, ServiceRegistry, SyncEngine
from tests.fakes import FakeSpotifyAdapter, FakeYouTubeMusicAdapter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def reset_fake_state():
    """Reset fake adapter state before each test."""
    FakeSpotifyAdapter.STATE = {}
    FakeYouTubeMusicAdapter.STATE = {}
    yield
    FakeSpotifyAdapter.STATE = {}
    FakeYouTubeMusicAdapter.STATE = {}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Provide isolated application settings for tests."""
    return Settings(
        bind_host="127.0.0.1",
        bind_port=8899,
        log_level="INFO",
        app_data_dir=tmp_path,
        auto_resume=False,
    )


@pytest.fixture
def app_state(settings: Settings) -> AppState:
    """Provide a fully wired application state backed by fakes."""
    db = Database(settings.db_path)
    db.initialize()
    registry = ServiceRegistry(settings)
    registry.register(FakeSpotifyAdapter.service, FakeSpotifyAdapter)
    registry.register(FakeYouTubeMusicAdapter.service, FakeYouTubeMusicAdapter)
    engine = SyncEngine(db, settings, registry)
    runner = JobRunner(engine, db)
    return AppState(
        settings=settings,
        db=db,
        registry=registry,
        engine=engine,
        runner=runner,
        pending_ytmusic_oauth={},
    )
