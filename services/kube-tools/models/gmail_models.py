

from dataclasses import dataclass

from pydantic import BaseModel, HttpUrl

from domain.google import GoogleEmailLabel


@dataclass
class TagModification:
    """Represents tag modifications for email messages."""
    to_add: list[GoogleEmailLabel]
    to_remove: list[GoogleEmailLabel]


class EmailTagManager:
    """Manages consistent email tag modifications."""

    @staticmethod
    def get_archive_tags() -> TagModification:
        """Tags for archiving emails."""
        return TagModification(
            to_add=[],
            to_remove=[GoogleEmailLabel.Inbox]
        )

    @staticmethod
    def get_processed_tags() -> TagModification:
        """Tags for marking emails as processed."""
        return TagModification(
            to_add=[GoogleEmailLabel.Starred],
            to_remove=[GoogleEmailLabel.Unread, GoogleEmailLabel.Inbox]
        )


class GmailConfig(BaseModel):
    base_url: HttpUrl
    sms_recipient: str
    concurrency: int
