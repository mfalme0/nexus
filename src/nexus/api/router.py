"""API router — aggregates all sub-routers."""

from fastapi import APIRouter

from nexus.api.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
