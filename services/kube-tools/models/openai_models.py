

from pydantic import BaseModel


class OpenAIConfig(BaseModel):
    """Pydantic model for OpenAI API configuration"""
    api_key: str
