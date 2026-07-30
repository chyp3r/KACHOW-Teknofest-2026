from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class SearchParam(BaseModel):
    """SOTA search query parameters input DTO."""
    query: str = Field(description="Search text query")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Metadata filters mapping")
    limit: int = Field(default=10, ge=1, le=100, description="Max search results to return")
