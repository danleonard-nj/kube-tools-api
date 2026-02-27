from pydantic import BaseModel, EmailStr


class StockMonitorConfig(BaseModel):
    ticker: str = 'AAPL'
    sell_threshold: float = 375.0
    floor_threshold: float = 300.0
    swing_percent: float = 0.05
    recipient_email: EmailStr = 'dcl525@gmail.com'
    backfill_min_samples: int = 50
