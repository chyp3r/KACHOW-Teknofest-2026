from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_db
from app.api.responses import APIResponse, SuccessResponse
from app.domains.users.schema.user_schema import UserCreate, UserResponse
from app.domains.users.repository import UserRepository
from app.domains.users.service import UserService
from app.domains.users.model.user_model import UserModel
from app.api.dependency import get_current_user

router = APIRouter(prefix="/users", tags=["users"])

@router.post("", response_model=APIResponse[UserResponse])
async def register(schema: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user account in the system."""
    repository = UserRepository(db)
    service = UserService(repository)
    user = await service.register_user(schema)
    response_data = UserResponse.model_validate(user)
    return SuccessResponse(data=response_data)

@router.get("/me", response_model=APIResponse[UserResponse])
async def get_me(current_user: UserModel = Depends(get_current_user)):
    """Get profile details of the currently authenticated user."""
    response_data = UserResponse.model_validate(current_user)
    return SuccessResponse(data=response_data)
