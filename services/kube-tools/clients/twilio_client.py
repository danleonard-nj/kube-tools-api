from framework.configuration import Configuration
from framework.logger import get_logger


logger = get_logger(__name__)

class TwilioClient:
    def __init__(
        self,
        configuration: Configuration
    ):
        self.__api_key = configuration.twilio.get('api_key')