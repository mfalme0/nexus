"""FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nexus.api.router import api_router
from nexus.config import settings
from nexus.db.engine import close_db, init_db
from nexus.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    configure_logging()
    logger.info("nexus.startup", env=settings.env.value)

    if settings.env.value in ("development", "testing"):
        try:
            await init_db()
            logger.info("nexus.db.initialized")
        except Exception as exc:
            logger.warning("nexus.db.init_failed", error=str(exc))

    yield

    await close_db()
    logger.info("nexus.shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="NEXUS",
        description="Autonomous Homelab Operations Agent",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.env.value != "production" else None,
        redoc_url="/redoc" if settings.env.value != "production" else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:3001"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api/v1")

    return app


app = create_app()
