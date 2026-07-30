from fastapi import APIRouter

from app.domains.auth.router import router as auth_router
from app.domains.chat.router import router as chat_router
from app.domains.documents.router import router as document_router
from app.domains.evaluation.router import router as evaluation_router
from app.domains.feedback.router import router as feedback_router
from app.domains.settings.router import router as settings_router
from app.domains.system.router import router as system_router, health_router
from app.domains.users.router import router as users_router

api_router = APIRouter()

# Register v1 routes
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(chat_router, tags=["chat"])
api_router.include_router(document_router, tags=["documents"])
api_router.include_router(evaluation_router, tags=["evaluation"])
api_router.include_router(feedback_router, tags=["feedback"])
api_router.include_router(settings_router, tags=["settings"])
api_router.include_router(system_router, tags=["system"])
api_router.include_router(users_router, tags=["users"])
