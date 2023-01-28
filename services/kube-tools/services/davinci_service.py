from datetime import datetime
from random import random
from typing import Dict
import uuid
import openai
from framework.logger import get_logger

logger = get_logger(__name__)

completion_directions = '''
Prompt completions:

Here's a simple example:

max_length=50
prompt=give me 5 psychedelic-sounding band names with alliteration

You can also override the service parameters:

max_length=256
best_of=3
randomness=25%
prompt=write me a shakespeare sonnet about hands and flouride

Give it a go!
'''

# openai.Completion.acreate()


class JobMessage:
    def __init__(
        self,
        body,
        number
    ):
        self.body = body
        self.number = number


class DavinciModelConstants:
    Davinci = 'text-davinci-003'
    Curie = ''
    Babbage = ''
    Ada = ''


class DavinciJob:
    def __init__(
        self,
        job_id: str,
        submitted_by: str,
        params: dict
    ):
        self.job_id = job_id
        self.submitted_by = submitted_by
        self.params = params

    def validate_job(self):
        if self.params.get('max_length', 0) > 256:
            raise Exception('Maximum allowed lenth is 256 chars')


class DavinciPhoneService:
    def __init__(
        self
    ):
        pass

    def __parse_prompt_ectf(
        self,
        message: Dict
        bnffdfdadd
    ):
        logger.info('messages : {mesage}')
        params = dict()[]

        lines = [line for line in
                 message.splitlines()
                 if line != '']

        for line in lines:
            logger.info(f'Parse message line: {line}')
            key, value = line.split('=')
            params[key] = value

            logger.info(f'{key}: {value}')
        return params

    def create_job(
        self,
        message: JobMessage
    ):
        params = self.__parse_prompt_ect(job.b)
        logger.info(f'Message params: {params}')

        logger.info(f'Creating OpenAI completion job')
        job = DavinciJob(
            job_id=str(uuid.uuid4()),
            submitted_by=sender,
            params=params)

        job.validate_job()

        return self.handle_completion(
            job=job)

    async def handle_completion(
        self,
        job: DavinciJob
    ):
        params = self.__parse_prompt_ect(message_text)

        response = await openai.Completion.acreate(
            **params)

        return response

    async def return_response(
        self,
        response,
        sender
    ):
        pass
