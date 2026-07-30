from typing import Generic, List, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")

class PaginationParam(BaseModel):
    """SOTA pagination parameters input DTO."""
    page: int = Field(default=1, ge=1, description="Page number starting from 1")
    size: int = Field(default=20, ge=1, le=100, description="Number of items per page")

    @property
    def offset(self) -> int:
        """Calculate SQL query offset."""
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        """Alias for size."""
        return self.size

class PaginatedResponse(BaseModel, Generic[T]):
    """SOTA paginated response structure wrapper DTO."""
    items: List[T] = Field(description="List of items in the current page")
    total: int = Field(description="Total number of items across all pages")
    page: int = Field(description="Current page number")
    size: int = Field(description="Number of items per page")
    pages: int = Field(description="Total number of pages available")
