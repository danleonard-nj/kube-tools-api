from framework.serialization import Serializable

from enum import StrEnum

from isort import file
from pydantic import BaseModel


class PermissionRole(StrEnum):
    """
    Enum class representing the roles for permissions in a drive.
    """

    OWNER = "owner"
    ORGANIZER = "organizer"
    FILE_ORGANIZER = "fileOrganizer"
    WRITER = "writer"
    COMMENTER = "commenter"
    READER = "reader"


class PermissionType(StrEnum):
    """
    Enum class representing the types of permissions for a resource.
    """

    USER = "user"
    GROUP = "group"
    DOMAIN = "domain"
    ANYONE = "anyone"


class GoogleDrivePermissionRequest(Serializable):
    def __init__(
        self,
        role: str,
        _type: str,
        value: str = None,
    ):
        self.role = role
        self.type = _type
        self.value = value

    def to_dict(self) -> dict:
        return {
            'role': self.role,
            'type': self.type,
            'value': self.value
        }


class GoogleDrivePermissionRequestModel(BaseModel, Serializable):
    role: str
    _type: str
    value: str

    def to_dict(self) -> dict:
        return {
            'role': self.role,
            'type': self.type,
            'value': self.value
        }


class GoogleDriveUploadRequest(Serializable):
    def __init__(
        self,
        name: str,
        upload_type: str = 'media',
        parents: list[str] = None
    ):
        self.upload_type = upload_type
        self.name = name
        self.parents = parents

    def to_dict(self) -> dict:
        data = {
            "uploadType": self.upload_type,
            "name": self.name,
            "supportsAllDrives": True,
        }

        if self.parents:
            data["parents"] = self.parents

        return data


class GoogleDriveUploadRequestModel(BaseModel, Serializable):
    name: str
    upload_type: str = 'media'
    parents: list[str] = None

    def to_dict(self) -> dict:
        data = {
            "uploadType": self.upload_type,
            "name": self.name,
            "supportsAllDrives": True,
        }

        if self.parents:
            data["parents"] = self.parents

        return data


class GoogleDriveUploadRequestModel(BaseModel, Serializable):
    name: str
    upload_type: str = 'media'
    parents: list[str] = None

    def to_dict(self) -> dict:
        data = {
            "uploadType": self.upload_type,
            "name": self.name,
            "supportsAllDrives": True,
        }

        if self.parents:
            data["parents"] = self.parents

        return data


class GoogleDriveFileExistsRequest(Serializable):
    def __init__(
        self,
        filename: str,
        directory_id: str = None,
        trashed=False
    ):
        self.directory_id = directory_id
        self.filename = filename
        self.trashed = trashed

    def to_dict(self) -> dict:
        if self.directory_id is None:
            return {
                'q': f"name = '{self.filename}' and trashed = {self.trashed}",
                'fields': 'files(id)',
                'pageSize': 1
            }

        return {
            'q': f"'{self.directory_id}' in parents and name = '{self.filename}' and trashed = {self.trashed}",
            'fields': 'files(id)',
            'pageSize': 1
        }


class GoogleDriveFileExistsRequestModel(BaseModel, Serializable):
    filename: str
    directory_id: str = None
    trashed: bool = False

    def to_dict(self) -> dict:
        if self.directory_id is None:
            return {
                'q': f"name = '{self.filename}' and trashed = {self.trashed}",
                'fields': 'files(id)',
                'pageSize': 1
            }

        return {
            'q': f"'{self.directory_id}' in parents and name = '{self.filename}' and trashed = {self.trashed}",
            'fields': 'files(id)',
            'pageSize': 1
        }


class GoogleDriveFileDetailsRequest(Serializable):
    def __init__(
        self,
        page_size: int = 100,
        fields: str = "nextPageToken, files(id, name, size, createdTime, modifiedTime)",
        order_by: str = "quotaBytesUsed desc",
        page_token: str = None
    ):
        self.page_size = page_size
        self.fields = fields
        self.order_by = order_by
        self.page_token = page_token

    def to_dict(self) -> dict:
        data = {
            "pageSize": self.page_size,
            "fields": self.fields,
            "orderBy": self.order_by,
        }

        if self.page_token:
            data["pageToken"] = self.page_token

        return data


class GoogleDriveFileDetailsRequestModel(BaseModel, Serializable):
    page_size: int = 100
    fields: str = "nextPageToken, files(id, name, size, createdTime, modifiedTime)"
    order_by: str = "quotaBytesUsed desc"
    page_token: str = None

    def to_dict(self) -> dict:
        data = {
            "pageSize": self.page_size,
            "fields": self.fields,
            "orderBy": self.order_by,
        }

        if self.page_token:
            data["pageToken"] = self.page_token

        return data
