import asyncio
import json
from typing import List

from aiogoogle import Aiogoogle
from aiogoogle.auth.creds import ClientCreds, UserCreds
from framework.clients.cache_client import CacheClientAsync
from framework.logger.providers import get_logger
from framework.serialization import Serializable

logger = get_logger(__name__)


def merge_dicts(dicts):
    result = dict()
    for _dict in dicts:
        result |= _dict
    return result


class AsyncHelper:
    @staticmethod
    def create_tasks(func, kwargs_list):
        tasks = []
        for kwargs in kwargs_list:
            task = asyncio.create_task(
                func(**kwargs))
            tasks.append(task)
        return tasks

    @staticmethod
    async def run_tasks(tasks):
        results = await asyncio.gather(
            *tasks)
        return results


class TokenFileCredential:
    def __init__(self, data):
        self.token = data.get('token')
        self.refresh_token = data.get('refresh_token')
        self.token_uri = data.get('token_uri')
        self.client_id = data.get('client_id')
        self.client_secret = data.get('client_secret')
        self.scopes = data.get('scopes')
        self.expiry = data.get('expiry')


class MessageListItem:
    def __init__(self, data):
        self.id = data.get('id')
        self.thread_id = data.get('threadId')


class MessageList(Serializable):
    def __init__(self, data):
        self.messages = self._parse_message_list(
            messages=data.get('messages'))

    def _parse_message_list(self, messages):
        return {
            message.get('id'): message
            for message in messages
        }

    def add_message_details(self, message_id, details):
        self.messages[message_id] = details

    @property
    def message_ids(self) -> List[str]:
        return list(self.messages.keys())

    def __getitem__(self, message_id):
        return self.messages[message_id]

    def __len__(self):
        return len(self.message_ids)


class GoogleClientBuilder:
    def __init__(self, token_filepath):
        self.creds = self._get_token_file_credential(
            token_filepath=token_filepath)

    def _get_token_file_credential(self, token_filepath) -> TokenFileCredential:
        with open(token_filepath, 'r') as file:
            token_file = json.loads(file.read())

        return TokenFileCredential(
            data=token_file)

    def _get_user_creds(self) -> UserCreds:
        return UserCreds(
            access_token=self.creds.token,
            refresh_token=self.creds.refresh_token,
            scopes=self.creds.scopes,
            token_uri=self.creds.token_uri)

    def _get_client_creds(self) -> ClientCreds:
        return ClientCreds(
            client_id=self.creds.client_id,
            client_secret=self.creds.client_secret,
            scopes=self.creds.scopes,
            redirect_uri='https://localhost:5050/')

    def build(self) -> Aiogoogle:
        return Aiogoogle(
            user_creds=self._get_user_creds(),
            client_creds=self._get_client_creds())


class GmailClient:
    def __init__(self, container):
        self.cache_client: CacheClientAsync = container.resolve(
            CacheClientAsync)

        self.client_provider = GoogleClientBuilder(
            token_filepath='token.json')

    def get_client(self):
        return self.client_provider.build()

    async def send_request(self, request):
        async with self.get_client() as client:
            gmail = await client.discover("gmail", "v1")
            request = request(gmail)
            return await client.as_user(request)

    async def get_emails(self, query, limit):
        logger.info(f'Query: {query}: Limit: {limit}')

        response = await self.send_request(
            request=lambda gmail: gmail.users.messages.list(
                q=query,
                userId='me',
                maxResults=limit))

        logger.info(f'Response: {response}')

        messages = MessageList(
            data=response)

        logger.info(f'Message count: {len(messages)}')
        func_kwargs = [{'message_id': message_id}
                       for message_id in messages.message_ids]

        tasks = AsyncHelper.create_tasks(
            func=self.get_email,
            kwargs_list=func_kwargs)

        results = await AsyncHelper.run_tasks(
            tasks=tasks)

        merged = merge_dicts(
            dicts=results)

        for message_id in messages.message_ids:
            logger.info(f'Mapping details to message')

            details = merged[message_id]

            messages.add_message_details(
                message_id=message_id,
                details=details)

        return messages.to_dict()

    async def get_email(self, message_id) -> dict[str, dict]:
        email = await self.send_request(
            request=lambda gmail: gmail.users.messages.get(
                userId='me',
                id=message_id))

        return {
            message_id: email
        }
