from pydantic import BaseModel


class AnthropicConfig(BaseModel):
    api_key: str