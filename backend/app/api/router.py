from fastapi import APIRouter

from app.domains.analytics.router import router as analytics_router
from app.domains.audit.router import router as audit_router
from app.domains.auth.router import router as auth_router
from app.domains.chat.router import router as chat_router
from app.domains.companies.router import router as companies_router
from app.domains.documents.router import router as document_router
from app.domains.drafts.router import router as drafts_router
from app.domains.feedback.router import company_router as feedback_company_router
from app.domains.feedback.router import router as feedback_router
from app.domains.notifications.router import router as notifications_router
from app.domains.pools.router import router as pools_router
from app.domains.companies.root_router import router as root_router
from app.domains.routing.router import router as routing_router
from app.domains.system.router import router as system_router, health_router
from app.domains.training.router import company_router as training_company_router
from app.domains.training.router import router as training_router
from app.domains.units.router import router as units_router
from app.domains.users.router import router as users_router

api_router = APIRouter()

# Register v1 routes
api_router.include_router(health_router, tags=["health"])
api_router.include_router(analytics_router, tags=["analytics"])
api_router.include_router(audit_router, tags=["audit"])
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(chat_router, tags=["chat"])
api_router.include_router(companies_router, tags=["companies"])
api_router.include_router(document_router, tags=["documents"])
api_router.include_router(drafts_router, tags=["drafts"])
api_router.include_router(feedback_router, tags=["feedback"])
api_router.include_router(feedback_company_router, tags=["feedback"])
api_router.include_router(notifications_router, tags=["notifications"])
api_router.include_router(pools_router, tags=["pools"])
api_router.include_router(root_router, tags=["root"])
api_router.include_router(routing_router, tags=["routing"])
api_router.include_router(system_router, tags=["system"])
api_router.include_router(training_router, tags=["training"])
api_router.include_router(training_company_router, tags=["training"])
api_router.include_router(units_router, tags=["units"])
api_router.include_router(users_router, tags=["users"])
