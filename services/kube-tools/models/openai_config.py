from typing import Optional

from pydantic import BaseModel


class OpenAIConfig(BaseModel):
    api_key: str
    admin_key: Optional[str] = None
