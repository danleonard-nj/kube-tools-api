from datetime import datetime, timedelta
from typing import Dict, List

from framework.serialization import Serializable
from utilities.utils import DateTimeUtil


class Queryable:
    def get_query(
        self
    ) -> dict:
        raise NotImplementedError()

    def get_sort(
        self
    ) -> list:
        return []


class MongoBackupConstants:
    ContainerName = 'mongo-dumps'
    DateTimeFormat = '%Y_%m_%d_%H_%M_%S'
    ExportFilepath = '/app/utilities/mongotools/bin/dump.gz'


class MongoDatabase:
    Podcasts = 'Podcasts'
    WeatherStation = 'WeatherStation'
    OpenAi = 'OpenAi'
    WellnessCheck = 'WellnessCheck'
    Sms = 'SMS'
    Gpt = 'GPT'
    Health = 'Health'
    MongoExport = 'MongoExport'
    ChatGPT = 'ChatGPT'
    Google = 'Google'


class MongoCollection:
    PodcastShows = 'Shows'
    WeatherStationCoordinate = 'StationCoordinate'
    WeatherStationZipLatLong = 'ZipLatLong'
    OpenAiRequest = 'OpenAiRequest'
    WellnessCheck = 'WellnessCheck'
    WellnessReply = 'WellnessReply'
    SmsConversations = 'SmsConversations'
    GptUserRequest = 'UserRequest'
    GptJob = 'GptJob'
    MongoExportHistory = 'MongoExportHistory'
    History = 'History'
    EmailServiceLog = 'EmailServiceLog'
    EmailRule = 'EmailRule'


class MongoExportPurgeResult(Serializable):
    def __init__(
        self,
        blob_name: str,
        created_date: datetime,
        days_old: float
    ):
        self.blob = blob_name
        self.created = created_date
        self.age = days_old


class MongoExportBlob:
    @property
    def created_timestamp(
        self
    ) -> int:
        return int(self.created_date.timestamp())

    @property
    def days_old(
        self
    ) -> float:

        return self.__get_days_old(
            now=int(datetime.now().timestamp()),
            created=self.created_timestamp)

    def __init__(
        self,
        data: Dict
    ):
        self.blob_name = data.get('name')
        self.created_date = data.get('creation_time')

    def __get_days_old(
        self,
        now: int,
        created: int
    ) -> float:

        delta = now - created
        if delta != 0:
            minutes = delta / 60
            hours = minutes / 60
            days = hours / 24
            return days
        return 0


class MongoExportResult(Serializable):
    def __init__(
        self,
        stdout: str,
        stderr: str,
        uploaded: Dict,
        purged: List[Dict]
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.uploaded = uploaded
        self.purged = purged


class MongoExportHistoryRecord(Serializable):
    def __init__(
        self,
        blob_name: str,
        elapsed: timedelta,
        stdout: str,
        stderr: str
    ):
        self.blob_name = blob_name
        self.elapsed = elapsed
        self.stdout = stdout
        self.stderr = stderr
        self.created_date = datetime.utcnow()


class MongoQuery:
    def get_query(
        self
    ) -> Dict:
        raise NotImplementedError()


class MongoTimestampRangeQuery(MongoQuery):
    def __init__(
        self,
        start_timestamp: int | None,
        end_timestamp: int | None = None,
        field_name: str | None = 'timestamp',
        left_inclusive: bool = True,
        right_inclusive: bool = True
    ):
        self.start_timestamp = start_timestamp
        self.end_timestamp = end_timestamp or DateTimeUtil.timestamp()
        self.field_name = field_name
        self.left_inclusive = left_inclusive
        self.right_inclusive = right_inclusive

    def get_query(
        self
    ):
        left_operator = '$gte' if self.left_inclusive else '$gt'
        right_operator = '$lte' if self.right_inclusive else '$lt'

        return {
            self.field_name: {
                left_operator: self.start_timestamp,
                right_operator: self.end_timestamp
            }
        }
