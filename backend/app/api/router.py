from fastapi import APIRouter

from app.api.v1.health import router as health_router

api_router = APIRouter()

# Register v1 routes
api_router.include_router(health_router, prefix="/v1", tags=["health"])
