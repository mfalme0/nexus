"""Pytest fixtures and configuration."""

import os
from collections.abc import AsyncGenerator

import pytest_asyncio

os.environ.setdefault("NEXUS_ENV", "testing")


@pytest_asyncio.fixture
async def client() -> AsyncGenerator:
    """Test client against the real FastAPI app with lifespan."""
    from httpx import ASGITransport, AsyncClient

    from nexus.main import create_app

    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
