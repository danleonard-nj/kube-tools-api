
from typing import Optional
from pydantic import BaseModel, EmailStr
from sib_api_v3_sdk import ApiClient
from sib_api_v3_sdk import Configuration as SibConfiguration
from sib_api_v3_sdk.api.transactional_emails_api import TransactionalEmailsApi
from sib_api_v3_sdk.models import SendSmtpEmail
from framework.logger import get_logger
from models.email_config import EmailConfig

logger = get_logger(__name__)


class EmailAddress(BaseModel):
    email: EmailStr
    name: Optional[str] = None


class SendInBlueClient:
    def __int__(
        self,
        email_config: EmailConfig
    ):
        self._email_config = email_config

        sib_config = SibConfiguration()
        sib_config.api_key['api-key'] = self._email_config.sendinblue_api_key.get_secret_value()
        self._sib_client = ApiClient(sib_config)
        self._sib_email_api = TransactionalEmailsApi(self._sib_client)

    async def send_email(
        self,
        recipient: str,
        subject: str,
        html_body: str,
        from_email: str = None,
        from_name: Optional[str] = None
    ) -> None:
        """Send email via Sendinblue API."""

        from_email = from_email or self._email_config.default_sender.email
        from_name = from_name or self._email_config.default_sender.name or 'KubeTools'

        logger.info(f"Sending email to {recipient} from {from_email}")

        sender = EmailAddress(
            email=from_email,
            name=from_name
        )

        to = EmailAddress(
            email=recipient
        )

        email = SendSmtpEmail(
            to=[to.model_dump()],
            sender=sender.model_dump(),
            subject=subject,
            html_content=html_body
        )

        self._sib_email_api.send_transac_email(email)
        logger.info(f"Email sent successfully to {recipient}")
