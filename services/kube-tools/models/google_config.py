from pydantic import BaseModel


class GoogleConfig(BaseModel):
    api_key: str
