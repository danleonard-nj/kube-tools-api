import base64
import io
from datetime import datetime
from typing import Any, Dict, List, Optional

from framework.crypto.hashing import md5
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from framework.serialization import Serializable
from framework.validators.nulls import none_or_whitespace
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaIoBaseUpload

logger = get_logger(__name__)

GMAIL_MESSAGE_URL = 'https://mail.google.com/mail/u/0/#inbox'


def update(current_value, new_value):
    if none_or_whitespace(new_value):
        return current_value
    if md5(str(current_value)) != md5(str(new_value)):
        return new_value
    return current_value


class GoogleEmailHeader:
    Subject = 'Subject'
    From = 'From'
    To = 'To'


class GoogleEmailLabel:
    Inbox = 'INBOX'
    Unread = 'UNREAD'
    Starred = 'STARRED'


class GmailRuleAction:
    Archive = 'archive'
    SMS = 'sms'
    Event = 'send-http'
    BankSync = 'bank-sync'
    Undefined = 'none'


class GoogleMapsException(Exception):
    def __init__(
        self,
        longitude: int,
        latitude: int
    ):
        super().__init__(
            f'Failed to fetch reverse geocode data for coordinate pair: {latitude}, {longitude}')


class GmailEmailHeaders(Serializable):
    def __init__(
        self,
        headers: List[Dict]
    ):
        self.__headers = self._build_index(
            headers=headers)

    def _build_index(
        self,
        headers: List[Dict]
    ):
        header_index = dict()

        for header in headers:
            name = header.get('name')
            header_index[name] = header.get('value')

        return header_index

    def __getitem__(
        self,
        key
    ):
        return self.__headers.get(key)

    def to_dict(self) -> Dict:
        return self.__headers


class GmailQueryResult(Serializable):
    def __init__(
        self,
        data
    ):
        self.messages = data.get('messages')
        self.next_page_token = data.get('nextPageToken')
        self.result_size_estimate = data.get('resultSizeEstimate')

        self.message_ids = self._get_message_ids(
            messages=self.messages)

    def _get_message_ids(
        self,
        messages
    ):
        if messages is not None:
            return [message_id.get('id')
                    for message_id in messages
                    if message_id is not None]
        else:
            return []

    @staticmethod
    def empty_result():
        return GmailQueryResult(
            data={
                'messages': [],
                'nextPageToken': None,
                'resultSizeEstimate': 0
            })


class GmailEmail(Serializable):
    @property
    def body(
        self
    ):
        if self.body_raw is None:
            return ''

        return base64.urlsafe_b64decode(
            self.body_raw)

    @property
    def timestamp(
        self
    ):
        return datetime.fromtimestamp(
            int(self.internal_date) / 1000)

    def __init__(
        self,
        data: Dict
    ):
        self.message_id = data.get('id')
        self.thread_id = data.get('threadId')
        self.label_ids = data.get('labelIds')
        self.snippet = data.get('snippet')
        self.internal_date = data.get('internalDate')

        self.raw = data

        self.body_raw = (
            data
            .get('payload', dict())
            .get('body', dict())
            .get('data', dict())
        )

        self.headers_raw = data.get('payload').get('headers')

        self.headers = GmailEmailHeaders(
            headers=self.headers_raw)

    def to_dict(self) -> Dict:
        return super().to_dict() | {
            'body': self.body,
            'timestamp': self.timestamp
        }

    def serializer_exclude(self):
        return ['body_raw',
                'internal_date',
                'headers_raw']


class UpdateEmailRuleRequest(Serializable):
    def __init__(
        self,
        data: Dict
    ):
        self.rule_id = data.get('rule_id')
        self.name = data.get('name')
        self.description = data.get('description')
        self.query = data.get('query')
        self.action = data.get('action')
        self.data = data.get('data')
        self.max_results = data.get('max_results')


class GmailEmailRule(Serializable):
    DefaultMaxResults = 10

    def __init__(
        self,
        rule_id: str,
        name: str,
        description: str,
        max_results: int,
        query: str,
        action: str,
        data: Any,
        created_date: datetime,
        count_processed: int = 0,
        modified_date: Optional[datetime] = None
    ):
        self.rule_id = rule_id
        self.name = name
        self.description = description
        self.max_results = (max_results
                            or self.DefaultMaxResults)
        self.query = query
        self.action = action
        self.data = data
        self.count_processed = count_processed
        self.modified_date = modified_date
        self.created_date = created_date

    def get_selector(
        self
    ) -> Dict:

        return {
            'rule_id': self.rule_id
        }

    def update_rule(
        self,
        update_request: UpdateEmailRuleRequest
    ) -> None:

        ArgumentNullException.if_none(update_request, 'update_request')

        self.name = update(self.name, update_request.name)
        self.description = update(self.description, update_request.description)
        self.max_results = update(self.max_results, update_request.max_results)
        self.query = update(self.query, update_request.query)
        self.action = update(self.action, update_request.action)
        self.data = update(self.data, update_request.data)

        self.modified_date = datetime.utcnow()

    @staticmethod
    def from_entity(data):
        return GmailEmailRule(
            rule_id=data.get('rule_id'),
            name=data.get('name'),
            description=data.get('description'),
            max_results=data.get('max_results'),
            query=data.get('query'),
            action=data.get('action'),
            data=data.get('data'),
            count_processed=data.get('count_processed'),
            created_date=data.get('created_date')
        )

    @staticmethod
    def from_request_body(data):
        return GmailEmailRule(
            rule_id=data.get('rule_id'),
            name=data.get('name'),
            description=data.get('description'),
            max_results=data.get('max_results'),
            query=data.get('query'),
            action=data.get('action'),
            data=data.get('data'),
            count_processed=data.get('count_processed'),
            created_date=data.get('created_date')
        )


class GoogleClientScope:
    Drive = ['https://www.googleapis.com/auth/drive']
    Gmail = ['https://www.googleapis.com/auth/gmail.modify']


class GoogleDriveDirectory:
    PodcastDirectoryId = '1jvoXhIvGLAn5DV73MK3IbcfQ6EF-L3qm'


class GoogleDriveFilePermission(Serializable):
    def __init__(
        self,
        _type: str = 'anyone',
        value: str = 'anyone',
        role: str = 'reader'
    ):
        self.type = _type
        self.value = value
        self.role = role


class GoogleDriveFileUpload:
    @property
    def data(self):
        return self.__data

    @property
    def metadata(self):
        return self.__metadata

    @property
    def media(self):
        return self.__get_media_io()

    def __init__(
        self,
        filename,
        data,
        mimetype,
        resumable=True,
        parent_directory=None
    ):
        self.__mimetype = mimetype
        self.__resumable = resumable
        self.__data = self.__get_stream(
            data=data)

        self.__metadata = self.__get_metadata(
            filename=filename,
            parent_directory=parent_directory)

    def __get_stream(
        self,
        data: bytes
    ) -> io.BytesIO:
        file = io.BytesIO(data)
        file.seek(0)

        return file

    def __get_media_io(self):
        return MediaIoBaseUpload(
            self.__data,
            mimetype=self.__mimetype,
            resumable=self.__resumable)

    def __get_metadata(
        self,
        filename: str,
        parent_directory: str
    ):
        file_metadata = {
            'name': filename,
        }

        if parent_directory is not None:
            file_metadata['parents'] = [
                parent_directory]

        return file_metadata

    def __exit__(self, *args, **kwargs):
        if not self.__data.closed:
            self.__data.close()


class EmailRuleLog(Serializable):
    def __init__(
        self,
        log_id: str,
        results: Dict,
        created_date: datetime
    ):
        self.log_id = log_id
        self.results = results
        self.created_date = created_date


def parse_gmail_body(
    message: GmailEmail
):
    # Recursively parse the message parts
    def parse_part(part):
        results = []
        parts_count = 0
        if 'body' in part and 'data' in part['body']:
            parts_count += 1
            logger.info(f'Parsing part: {parts_count}')
            results.append(part['body']['data'])
        if 'parts' in part:
            for subpart in part['parts']:
                logger.info(f'Parsing subpart')
                results.extend(parse_part(subpart))
        return results

    data = message.raw
    payload = data.get('payload', {})
    results = parse_part(payload)

    decoded = [base64.urlsafe_b64decode(
        result.encode()).decode()
        for result in results]

    return decoded


def get_key(
    client_id: str,
    scopes: List[str]
) -> str:
    scopes = '-'.join(scopes)
    return f'{client_id}-{scopes}'


class AuthClient(Serializable):
    def __init__(
        self,
        client_key: str,
        token: str,
        refresh_token: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        scopes: List[str],
        expiry: str,
        timestamp: str
    ):
        self.client_key = client_key
        self.token = token
        self.refresh_token = refresh_token
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes
        self.expiry = expiry
        self.timestamp = timestamp

    @staticmethod
    def from_client(
        client: Credentials
    ):
        key = get_key(
            client_id=client.client_id,
            scopes=client.scopes)

        logger.info(f'Creating auth client: {key}')

        return AuthClient(
            client_key=key,
            token=client.token,
            refresh_token=client.refresh_token,
            token_url=client.token_uri,
            client_id=client.client_id,
            client_secret=client.client_secret,
            expiry=client.expiry.isoformat(),
            timestamp=datetime.now().isoformat(),
            scopes=client.scopes
        )

    @staticmethod
    def from_entity(
        data: dict
    ):
        client_key = data.get('client_key')

        if client_key is None or client_key == '':
            logger.info(f'No client key found, generating new key')
            client_key = get_key(
                client_id=data.get('client_id'),
                scopes=data.get('scopes'))

        return AuthClient(
            client_key=client_key,
            token=data.get('token'),
            refresh_token=data.get('refresh_token'),
            token_url=data.get('token_uri'),
            client_id=data.get('client_id'),
            client_secret=data.get('client_secret'),
            scopes=data.get('scopes'),
            expiry=data.get('expiry'),
            timestamp=data.get('timestamp')
        )

    def get_selector(
        self
    ):
        return {
            'client_id': self.client_id
        }

    def get_credentials(
        self,
        scopes: List[str]
    ):
        info = self.to_dict() | {
            'scopes': scopes
        }

        return Credentials.from_authorized_user_info(
            info=info,
            scopes=scopes)


class ProcessGmailRuleResponse(Serializable):
    def __init__(
        self,
        status: str,
        rule: GmailEmailRule,
        affected_count: int = None
    ):
        self.status = status
        self.rule = rule

        self.affected_count = (
            affected_count or 0
        )


class GmailServiceRunResult(Serializable):
    def __init__(
        self,
        rule_id: str,
        rule_name: str,
        affected_count: int
    ):
        self.rule_id = rule_id
        self.rule_name = rule_name
        self.affected_count = affected_count

    @staticmethod
    def from_response(
        response: ProcessGmailRuleResponse
    ):
        return GmailServiceRunResult(
            rule_id=response.rule.rule_id,
            rule_name=response.rule.name,
            affected_count=response.affected_count
        )


class ProcessGmailRuleRequest(Serializable):
    def __init__(
        self,
        rule: GmailEmailRule
    ):
        self.rule = rule

    @staticmethod
    def from_rule(
        rule
    ):
        return ProcessGmailRuleRequest(
            rule=rule)


class CreateEmailRuleRequest(Serializable):
    def __init__(
        self,
        data: Dict
    ):
        self.name = data.get('name')
        self.description = data.get('description')
        self.query = data.get('query')
        self.action = data.get('action')
        self.data = data.get('data')
        self.max_results = data.get('max_results')


class DeleteGmailEmailRuleResponse(Serializable):
    def __init__(
        self,
        result: bool
    ):
        self.result = result


class GmailModifyEmailRequest(Serializable):
    def __init__(
        self,
        add_label_ids: List = [],
        remove_label_ids: List = []
    ):
        self.add_label_ids = add_label_ids
        self.remove_label_ids = remove_label_ids

    def to_dict(self) -> Dict:
        return {
            "addLabelIds": self.add_label_ids,
            "removeLabelIds": self.remove_label_ids
        }
