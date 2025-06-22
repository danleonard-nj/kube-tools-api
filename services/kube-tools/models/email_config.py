from typing import Optional
from pydantic import BaseModel, EmailStr, SecretStr


class EmailAddressConfig(BaseModel):
    email: EmailStr
    name: Optional[str] = None


class EmailConfig(BaseModel):
    from_email: EmailStr
    sendinblue_api_key: SecretStr
    default_sender: Optional[EmailAddressConfig] = None
