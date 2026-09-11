"""Health check endpoint."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from nexus.config import settings
from nexus.db.engine import async_session

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Health check with database connectivity verification."""
    result: dict[str, Any] = {
        "status": "healthy",
        "version": "0.1.0",
        "environment": settings.env.value,
        "timestamp": datetime.now(UTC).isoformat(),
        "checks": {},
    }

    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        result["checks"]["database"] = "healthy"
    except Exception as e:
        result["status"] = "degraded"
        result["checks"]["database"] = f"unhealthy: {type(e).__name__}"

    return result
