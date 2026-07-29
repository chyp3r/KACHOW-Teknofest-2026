from fastapi import APIRouter

from app.api.responses import SuccessResponse
from app.core.config import settings

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint returning standardized APIResponse."""
    data = {
        "status": "healthy",
        "project": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
    }
    return SuccessResponse(data=data)
