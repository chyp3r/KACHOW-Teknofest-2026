from fastapi import APIRouter

from app.domains.auth.router import router as auth_router
from app.domains.chat.router import router as chat_router
from app.domains.companies.router import router as companies_router
from app.domains.documents.router import router as document_router
from app.domains.drafts.router import router as drafts_router
from app.domains.routing.router import router as routing_router
from app.domains.system.router import router as system_router, health_router
from app.domains.units.router import router as units_router
from app.domains.users.router import router as users_router

api_router = APIRouter()

# Register v1 routes
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(chat_router, tags=["chat"])
api_router.include_router(companies_router, tags=["companies"])
api_router.include_router(document_router, tags=["documents"])
api_router.include_router(drafts_router, tags=["drafts"])
api_router.include_router(routing_router, tags=["routing"])
api_router.include_router(system_router, tags=["system"])
api_router.include_router(units_router, tags=["units"])
api_router.include_router(users_router, tags=["users"])
