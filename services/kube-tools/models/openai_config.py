from pydantic import BaseModel


class OpenAIConfig(BaseModel):
    api_key: str
