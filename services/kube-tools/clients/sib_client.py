
import base64
from typing import Optional
from pydantic import BaseModel, EmailStr
from sib_api_v3_sdk import ApiClient
from sib_api_v3_sdk import Configuration as SibConfiguration
from sib_api_v3_sdk.api.transactional_emails_api import TransactionalEmailsApi
from sib_api_v3_sdk.models import SendSmtpEmail, SendSmtpEmailAttachment
from framework.logger import get_logger
from models.email_config import EmailConfig

logger = get_logger(__name__)


class EmailAddress(BaseModel):
    email: EmailStr
    name: Optional[str] = None


class SendInBlueClient:
    def __init__(
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

        default_sender = self._email_config.default_sender
        from_email = from_email or (default_sender.email if default_sender else self._email_config.from_email)
        from_name = from_name or (default_sender.name if default_sender else None) or 'KubeTools'

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

    async def send_email_with_inline_image(
        self,
        recipient: str,
        subject: str,
        html_body: str,
        image_bytes: bytes,
        image_filename: str = 'chart.png',
        image_content_id: str = 'chart_cid',
        from_email: str = None,
        from_name: Optional[str] = None
    ) -> None:
        """Send email with an inline image embedded via Content-ID.

        The html_body should reference the image as:
            <img src="cid:chart_cid">
        """
        await self.send_email_with_inline_images(
            recipient=recipient,
            subject=subject,
            html_body=html_body,
            images=[{
                'bytes': image_bytes,
                'filename': image_filename,
                'content_id': image_content_id,
            }],
            from_email=from_email,
            from_name=from_name)

    async def send_email_with_inline_images(
        self,
        recipient: str,
        subject: str,
        html_body: str,
        images: list[dict],
        from_email: str = None,
        from_name: Optional[str] = None
    ) -> None:
        """Send email with multiple inline images.

        images: list of dicts with keys 'bytes', 'filename', 'content_id'.
        The html_body should reference each image as:
            <img src="cid:{content_id}">
        """

        default_sender = self._email_config.default_sender
        from_email = from_email or (default_sender.email if default_sender else self._email_config.from_email)
        from_name = from_name or (default_sender.name if default_sender else None) or 'KubeTools'

        logger.info(f"Sending email with {len(images)} inline image(s) to {recipient}")

        sender = EmailAddress(
            email=from_email,
            name=from_name
        )

        to = EmailAddress(
            email=recipient
        )

        attachments = []
        for img in images:
            b64_content = base64.b64encode(img['bytes']).decode('utf-8')
            attachments.append(SendSmtpEmailAttachment(
                content=b64_content,
                name=img['filename']
            ))

        email = SendSmtpEmail(
            to=[to.model_dump()],
            sender=sender.model_dump(),
            subject=subject,
            html_content=html_body,
            attachment=attachments
        )

        self._sib_email_api.send_transac_email(email)
        logger.info(f"Email with inline image(s) sent successfully to {recipient}")
