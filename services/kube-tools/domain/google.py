import base64
import io
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from framework.crypto.hashing import md5
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from framework.serialization import Serializable
from framework.validators.nulls import none_or_whitespace
from googleapiclient.http import MediaIoBaseUpload
from openai import BaseModel
from utilities.utils import ValueConverter, clean_unicode

logger = get_logger(__name__)

GMAIL_MESSAGE_URL = 'https://mail.google.com/mail/u/0/#inbox'
DEFAULT_PROMPT_TEMPLATE = 'Summarize this email in a few sentences, including any cost info and relevant dates/times or other useful information'


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
        self._headers = self._build_index(
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
        return self._headers.get(key)

    def to_dict(self) -> Dict:
        return self._headers


class GmailQueryResultModel(BaseModel, Serializable):
    messages: List[Dict] = []
    nextPageToken: Optional[str] = None  # Make this field optional and default to None
    resultSizeEstimate: Optional[int] = 0

    @property
    def count(
        self
    ):
        return len(self.message_ids)

    @property
    def message_ids(
        self
    ):
        return self._get_message_ids(
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
        return GmailQueryResultModel(
            messages=[],
            nextPageToken=None,
            resultSizeEstimate=0
        )


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


# class UpdateEmailRuleRequest(Serializable):
#     def __init__(
#         self,
#         data: Dict
#     ):
#         self.rule_id = data.get('rule_id')
#         self.name = data.get('name')
#         self.description = data.get('description')
#         self.query = data.get('query')
#         self.action = data.get('action')
#         self.data = data.get('data')
#         self.max_results = data.get('max_results')


class UpdateEmailRuleRequestModel(BaseModel, Serializable):
    rule_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    query: Optional[str] = None
    action: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    max_results: Optional[int] = None

    @staticmethod
    def from_dict(
        data: Dict
    ):
        return UpdateEmailRuleRequestModel(
            rule_id=data.get('rule_id'),
            name=data.get('name'),
            description=data.get('description'),
            query=data.get('query'),
            action=data.get('action'),
            data=data.get('data'),
            max_results=data.get('max_results')
        )


class GmailEmailRuleDataModel(BaseModel, Serializable):
    bank_sync_bank_key: Optional[str] = None
    bank_sync_alert_type: Optional[str] = None

    chat_gpt_include_summary: Optional[bool] = None
    chat_gpt_prompt_template: Optional[str] = None

    sms_additional_recipients: Optional[List[str]] = None


class GmailEmailRuleModel(BaseModel, Serializable):
    rule_id: str
    name: str
    description: str
    max_results: int = 10
    query: str
    action: str
    data: Any
    created_date: datetime
    count_processed: int = 0
    last_processed_date: Optional[datetime] = None
    modified_date: Optional[datetime] = None

    def get_selector(
        self
    ) -> Dict:

        return {
            'rule_id': self.rule_id
        }

    def update_rule(
        self,
        update_request: UpdateEmailRuleRequestModel
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
        config = GmailEmailRuleDataModel.model_validate(data.get('data', {}))

        return GmailEmailRuleModel(
            rule_id=data.get('rule_id'),
            name=data.get('name'),
            description=data.get('description'),
            max_results=data.get('max_results'),
            query=data.get('query'),
            action=data.get('action'),
            data=config,
            count_processed=data.get('count_processed'),
            last_processed_date=data.get('last_processed_date'),
            created_date=data.get('created_date')
        )

    @staticmethod
    def from_request_body(data):
        config = GmailEmailRuleDataModel.model_validate(data.get('data', {}))

        return GmailEmailRuleModel(
            rule_id=data.get('rule_id'),
            name=data.get('name'),
            description=data.get('description'),
            max_results=data.get('max_results'),
            query=data.get('query'),
            action=data.get('action'),
            data=config,
            count_processed=data.get('count_processed'),
            last_processed_date=data.get('last_processed_date'),
            created_date=data.get('created_date')
        )


class GoogleClientScope:
    Drive = 'https://www.googleapis.com/auth/drive'
    Gmail = 'https://mail.google.com/'


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
        return self._data

    @property
    def metadata(self):
        return self._metadata

    @property
    def media(self):
        return self._get_media_io()

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
        self._data = self._get_stream(
            data=data)

        self._metadata = self._get_metadata(
            filename=filename,
            parent_directory=parent_directory)

    def _get_stream(
        self,
        data: bytes
    ) -> io.BytesIO:
        file = io.BytesIO(data)
        file.seek(0)

        return file

    def _get_media_io(self):
        return MediaIoBaseUpload(
            self._data,
            mimetype=self.__mimetype,
            resumable=self.__resumable)

    def _get_metadata(
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
        if not self._data.closed:
            self._data.close()


class EmailRuleLogType:
    RULE_EXECUTION = "rule_execution"
    EMAIL_PROCESSING = "email_processing"
    ERROR = "error"
    PERFORMANCE_METRIC = "performance_metric"


class EmailRuleExecutionLog(BaseModel, Serializable):
    log_id: str
    log_type: Optional[str] = EmailRuleLogType.RULE_EXECUTION
    rule_id: str
    rule_name: str
    execution_id: str
    status: str
    start_time: datetime
    end_time: Optional[datetime] = None
    emails_found: Optional[int] = None
    emails_processed: Optional[int] = None
    emails_failed: Optional[int] = None
    error_message: Optional[str] = None
    execution_duration_ms: Optional[int] = None
    created_date: Optional[datetime] = None


class EmailProcessingLog(BaseModel, Serializable):
    log_id: str
    log_type: Optional[str] = EmailRuleLogType.EMAIL_PROCESSING
    rule_id: str
    rule_name: Optional[str] = None
    email_id: str
    email_subject: str
    email_from: str
    labels_ids: Optional[List[str]] = None
    action_type: str
    status: str
    processing_time_ms: Optional[int] = None
    error_message: Optional[str] = None
    action_details: Optional[Dict] = None
    created_date: Optional[datetime] = None


class EmailRuleErrorLog(BaseModel, Serializable):
    log_id: str
    log_type: Optional[str] = EmailRuleLogType.ERROR
    execution_id: Optional[str]
    rule_id: Optional[str]
    email_id: Optional[str]
    error_type: str
    error_message: str
    stack_trace: Optional[str] = None
    context: Optional[Dict] = None
    created_date: Optional[datetime] = None


class EmailRulePerformanceLog(BaseModel, Serializable):
    log_id: str
    log_type: Optional[str] = EmailRuleLogType.PERFORMANCE_METRIC
    execution_id: str
    rule_id: str
    metric_name: str
    metric_value: float
    metric_unit: str
    additional_data: Optional[Dict] = None
    created_date: Optional[datetime] = None


# Legacy model - keeping for backward compatibility
class EmailRuleLog(BaseModel, Serializable):
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


def strip_special_chars(value: str) -> str:
    return (
        value
        .strip()
        .replace('\n', ' ')
        .replace('\t', ' ')
        .replace('\r', ' ')
    )


def parse_gmail_body_text(
    message: GmailEmail
) -> List[str]:

    segments = parse_gmail_body(
        message=message)

    results = []

    for segment in segments:
        if none_or_whitespace(segment):
            continue

        # Parse the segment as HTML
        soup = BeautifulSoup(segment)

        # Get the body of the email
        body = soup.find('body')

        # If there is no body in this HTML segment
        # then skip it and move on to the next one
        if none_or_whitespace(body):
            continue

        # Get the text content of the body and strip
        # any newlines, tabs, or carriage returns
        content = strip_special_chars(
            clean_unicode(
                unicodedata.normalize(
                    'NFKD', body.get_text())))

        results.append(content)

    return results


def get_key(
    client_id: str,
    scopes: List[str]


) -> str:
    scopes = '-'.join(scopes)
    return f'{client_id}-{scopes}'


class ProcessGmailRuleResponse(Serializable):
    def __init__(
        self,
        status: str,
        rule: GmailEmailRuleModel,
        affected_count: int = None
    ):
        self.rule_id = rule.rule_id
        self.rule_name = rule.name
        self.status = status

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
    def __init(
        self,
        rule: GmailEmailRuleModel
    ):
        self.rule = rule

    @staticmethod
    def from_rule(
        rule
    ):
        return ProcessGmailRuleRequest(
            rule=rule)


class ProcessGmailRuleRequest(BaseModel, Serializable):
    rule: GmailEmailRuleModel


class CreateEmailRuleRequestModel(BaseModel, Serializable):
    name: str
    description: str
    query: str
    action: str
    data: Optional[Dict[str, Any]] = None
    max_results: int = 10

    @staticmethod
    def from_dict(
        data: Dict
    ):
        return CreateEmailRuleRequestModel(
            name=data.get('name'),
            description=data.get('description'),
            query=data.get('query'),
            action=data.get('action'),
            data=data.get('data'),
            max_results=data.get('max_results', 10)
        )


class DeleteGmailEmailRuleResponseModel(BaseModel, Serializable):
    result: bool


class GmailModifyEmailRequestModel(BaseModel, Serializable):
    add_label_ids: List[str] = []
    remove_label_ids: List[str] = []

    def to_dict(self) -> Dict:
        return {
            'addLabelIds': self.add_label_ids,
            'removeLabelIds': self.remove_label_ids
        }


class GmailModifyEmailRequestModel(BaseModel, Serializable):
    add_label_ids: List[str] = []
    remove_label_ids: List[str] = []

    def to_dict(self) -> Dict:
        return {
            'addLabelIds': self.add_label_ids,
            'removeLabelIds': self.remove_label_ids
        }


class GoogleDriveReportModel(Serializable):
    def __init__(
        self,
        id: str,
        name: str,
        created_time: str,
        modified_time: str,
        size_bytes: int = 0
    ):
        self.id = id
        self.name = name
        self.created_time = created_time
        self.modified_time = modified_time
        self.size_mb = ValueConverter.bytes_to_megabytes(
            int(size_bytes))

    @staticmethod
    def from_response(
        data: dict
    ):
        return GoogleDriveReportModel(
            id=data.get('id'),
            name=data.get('name'),
            created_time=data.get('createdTime'),
            modified_time=data.get('modifiedTime'),
            size_bytes=data.get('size'))


class GetTokenResponse(Serializable):
    def __init__(
        self,
        token: str
    ):
        self.token = token

    @staticmethod
    def from_entity(
        data: dict
    ):
        return GetTokenResponse(
            token=data.get('token'))

    @staticmethod
    def from_credentials(
        creds
    ):
        return GetTokenResponse(
            token=creds.token)
