from pydantic import BaseModel
from typing import List, Optional


class PlaidConfig(BaseModel):
    base_url: str
    client_id: str
    client_secret: str


class PlaidAccountConfig(BaseModel):
    bank_key: str
    access_token: str
    account_id: str
    sync_threshold_minutes: int


class CoinbaseAccountConfig(BaseModel):
    currency_code: str
    bank_key: str


class BankingConfig(BaseModel):
    age_cutoff_threshold_days: int = 90
    balance_sync_gpt_model: Optional[str] = 'gpt-4o-mini'
    plaid_accounts: List[PlaidAccountConfig]
    coinbase_accounts: List[CoinbaseAccountConfig]
