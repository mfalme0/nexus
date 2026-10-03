"""API router — aggregates all sub-routers."""

from fastapi import APIRouter

from nexus.api.health import router as health_router
from nexus.api.inventory import router as inventory_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(inventory_router)
