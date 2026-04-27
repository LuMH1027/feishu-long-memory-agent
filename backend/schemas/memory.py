from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class MemoryCreate(BaseModel):
    content: str
    type: str
    source: str
    user_id: Optional[str] = None
    team_id: Optional[str] = None


class MemoryRetrieveRequest(BaseModel):
    query: str
    top_k: Optional[int] = None
    threshold: Optional[float] = None


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content: str
    type: str
    source: str
    user_id: Optional[str] = None
    team_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    expire_at: Optional[datetime] = None
    hit_count: int = 0
