from datetime import datetime
from typing import Dict

from framework.logger import get_logger
from framework.serialization import Serializable
from utilities.utils import ValueConverter

logger = get_logger(__name__)


def format_row(data): return {
    'active_image': data,
    'is_active': True
}


def format_result_row(data, repo): return (
    data.to_dict() | {
        'repo_name': repo,
        'size_mb': ValueConverter.bytes_to_megabytes(
            bytes=data.image_size)
    }
)


class AcrImage(Serializable):
    def __init__(
        self,
        id: str,
        tag: str,
        image_size: int,
        created_date: datetime
    ):
        self.id = id
        self.tag = tag
        self.image_size = image_size
        self.created_date = created_date

    @staticmethod
    def from_dict(
        data: dict
    ):
        return AcrImage(
            id=data.get('id'),
            tag=data.get('tag'),
            image_size=data.get('image_size'),
            created_date=data.get('created_date'))

    @staticmethod
    def from_manifest(data: dict):
        # Get the tag from the tags list
        tag = data.get('tags', ['no-tag'])[0]

        return AcrImage(
            id=data.get('digest'),
            tag=tag,
            image_size=data.get('imageSize'),
            created_date=data.get('createdTime')
        )
