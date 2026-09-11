"""Configuration tests."""

import pytest

from nexus.config import NexusSettings, settings


@pytest.mark.unit
def test_settings_exposes_database_url() -> None:
    url = settings.database.async_url
    assert url.startswith("postgresql+asyncpg://")
    assert "nexus" in url


@pytest.mark.unit
def test_settings_environment_defaults_to_development() -> None:
    s = NexusSettings()
    # settings module-level instance may differ; check the default class behavior
    assert s.env.value in ("development", "testing")
