from pydantic import BaseModel


class CronGenerateRequest(BaseModel):
    prompt: str


class CronFieldDetail(BaseModel):
    field: str
    value: str


class CronGenerateResult(BaseModel):
    expression: str
    description: str
    fields: list[CronFieldDetail]
    tokens_used: int
