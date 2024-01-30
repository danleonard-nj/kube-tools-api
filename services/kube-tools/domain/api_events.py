from framework.serialization import Serializable


class ApiEventAlert(Serializable):
    def __init__(
        self,
        event_id: str,
        key: str,
        endpoint: str,
        status_code: int,
        event_date: int
    ):
        self.event_id = event_id
        self.key = key
        self.endpoint = endpoint
        self.status_code = status_code
        self.event_date = event_date

    @staticmethod
    def from_event(data):
        return ApiEventAlert(
            event_id=data.get('log_id'),
            key=data.get('key'),
            endpoint=data.get('endpoint'),
            status_code=data.get('status_code'),
            event_date=data.get('timestamp'))

    @staticmethod
    def from_entity(data):
        return ApiEventAlert(
            event_id=data.get('event_id'),
            key=data.get('key'),
            endpoint=data.get('endpoint'),
            status_code=data.get('status_code'),
            event_date=data.get('event_date'))

