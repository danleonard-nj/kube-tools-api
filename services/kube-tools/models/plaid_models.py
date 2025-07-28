from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class AccountBalance(BaseModel):
    available: Optional[float] = None
    current: Optional[float] = None
    iso_currency_code: Optional[str] = None
    unofficial_currency_code: Optional[str] = None
    limit: Optional[float] = None
    last_updated_datetime: Optional[str] = None


class Account(BaseModel):
    account_id: str
    access_token: str
    name: str
    official_name: Optional[str] = None
    type: str
    subtype: Optional[str] = None
    balances: AccountBalance
    mask: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Transaction(BaseModel):
    transaction_id: str
    account_id: str
    access_token: str
    amount: float
    date: datetime
    name: str
    category: Optional[list[str]] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SyncState(BaseModel):
    access_token: str
    cursor: str = ""
    last_sync: Optional[datetime] = None
