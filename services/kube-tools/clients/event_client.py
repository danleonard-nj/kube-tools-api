from azure.servicebus import ServiceBusMessage, TransportType, ServiceBusClient
from framework.configuration.configuration import Configuration
from framework.logger.providers import get_logger

logger = get_logger(__name__)


class EventClient:
    def __init__(
        self,
        configuration: Configuration
    ):
        connecion_string = configuration.service_bus.get(
            'connection_string')

        self.__queue_name = configuration.service_bus.get(
            'queue_name')
        self.__client = ServiceBusClient.from_connection_string(
            conn_str=connecion_string,
            logging_enable=True,
            transport_type=TransportType.Amqp)

        self.__sender = self.__client.get_queue_sender(
            queue_name=self.__queue_name)

    def send_messages(
        self,
        messages: list[ServiceBusMessage]
    ) -> None:
        '''
        Send a batch of service bus messages
        '''

        logger.info(f'Getting service bus queue sender')

        # TODO: Batch the mesages batches to prevent exceeding max batch size
        batch = self.__sender.create_message_batch()
        for message in messages:
            logger.info(
                f'Adding message to batch: {message.message_id}: {message.correlation_id}')
            batch.add_message(message)

        self.__sender.send_messages(batch)
        logger.info(f'Messages sent successfully')

    def send_message(
        self,
        message: ServiceBusMessage
    ) -> None:
        '''
        Send a service bus message
        '''

        logger.info(f'Dispatching event message')

        self.__sender.send_messages(
            message=message)

        logger.info(f'Message sent successfully')
