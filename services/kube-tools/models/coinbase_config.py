from typing import List
from pydantic import BaseModel


class CoinbaseConfig(BaseModel):
    name: str
    secret: str
    currencies: List[str]
