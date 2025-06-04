from pydantic import BaseModel, EmailStr, SecretStr


class EmailConfig(BaseModel):
    from_email: EmailStr
    sendinblue_api_key: SecretStr
