from typing import List, Optional, Dict, Any
from bson import ObjectId
from datetime import datetime

from pydantic import BaseModel, Field


class PlaidAccountModel(BaseModel):
    name: str
    mask: Optional[str] = None
    type: str
    subtype: Optional[str] = None
    verification_status: Optional[str] = None
    class_type: Optional[str] = None


class PlaidItemModel(BaseModel):
    item_id: str
    access_token: str
    public_token: str
    institution_name: str
    institution_id: str
    date_linked: datetime
    last_sync: datetime
    status: str
    environment: str
    config: Dict[str, Any] = Field(default_factory=dict)
    accounts: List[PlaidAccountModel] = Field(default_factory=list)
