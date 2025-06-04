from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime


class Balance(BaseModel):
    @property
    def parsed_balance(self) -> float:
        return float(self.value)

    value: str
    currency: str


class CoinbaseAccount(BaseModel):
    uuid: str
    name: str
    currency: str
    available_balance: Balance
    balance: Optional[float] = None  # Coinbase API returns balance as a string, so we use Optional[float]
    default: bool
    active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]
    type: str
    ready: bool
    hold: Balance
    retail_portfolio_id: str
    platform: str
    usd_exchange: Optional[float] = None
    usd_amount: Optional[float] = None
