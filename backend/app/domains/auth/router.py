from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_db
from app.api.responses import APIResponse, SuccessResponse
from app.domains.auth.schema.auth_schema import LoginRequest, TokenResponse
from app.domains.users.repository import UserRepository
from app.domains.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=APIResponse[TokenResponse])
async def login(schema: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate user credentials and issue access tokens."""
    user_repository = UserRepository(db)
    service = AuthService(user_repository)
    token_response = await service.authenticate_user(schema)
    return SuccessResponse(data=token_response)
