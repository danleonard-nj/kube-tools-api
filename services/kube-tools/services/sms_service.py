import json

from azure.servicebus import ServiceBusClient, ServiceBusMessage
from framework.configuration.configuration import Configuration
from framework.logger.providers import get_logger

logger = get_logger(__name__)


class SmsService:
    def __init__(
        self,
        configuration: Configuration
    ):
        connecion_string = configuration.service_bus.get(
            'connection_string')

        self.__client = ServiceBusClient.from_connection_string(
            conn_str=connecion_string)

        self.__sender = self.__client.get_queue_sender(
            queue_name='sms-twilio')

    def handle_message(
        self,
        message
    ):
        logger.info('Handling event message')
        service_bus_message = ServiceBusMessage(
            body=json.dumps(message))

        logger.info(f'Message: {service_bus_message}')

        self.__sender.send_messages(
            message=service_bus_message)
        logger.info(f'Message sent successfully')
