from cron_descriptor import get_description
from croniter import croniter

from clients.gpt_client import GPTClient
from domain.scheduler import CronFieldDetail, CronGenerateResult
from framework.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    'You are a CRON expression generator. '
    'Given a natural language schedule description, respond with ONLY the CRON expression. '
    'Use 5 fields (minute hour day-of-month month day-of-week) for minute-granularity schedules. '
    'Use 6 fields (second minute hour day-of-month month day-of-week) when seconds precision is needed. '
    'No explanation, no markdown, no extra text whatsoever. '
    'Examples:\n'
    '  "every hour" → 0 * * * *\n'
    '  "every day at 2pm" → 0 14 * * *\n'
    '  "every weekday at 9am" → 0 9 * * 1-5\n'
    '  "every 15 minutes" → */15 * * * *\n'
    '  "every 30 seconds" → */30 * * * * *\n'
    '  "every 10 seconds on weekdays" → */10 * * * * 1-5'
)

_FIELD_NAMES_5 = ['minute', 'hour', 'day-of-month', 'month', 'day-of-week']
_FIELD_NAMES_6 = ['second', 'minute', 'hour', 'day-of-month', 'month', 'day-of-week']


class SchedulerServiceError(Exception):
    pass


def _validate_and_parse(expression: str) -> list[CronFieldDetail]:
    if not croniter.is_valid(expression):
        raise SchedulerServiceError(f'Invalid CRON expression: "{expression}"')

    parts = expression.strip().split()
    field_names = _FIELD_NAMES_6 if len(parts) == 6 else _FIELD_NAMES_5
    return [
        CronFieldDetail(field=field_names[i], value=parts[i])
        for i in range(len(parts))
    ]


class SchedulerService:
    def __init__(self, gpt_client: GPTClient):
        self._gpt = gpt_client

    async def generate_cron(self, prompt: str) -> CronGenerateResult:
        logger.info(f'Generating CRON expression for prompt: {prompt!r}')

        result = await self._gpt.generate_completion(
            prompt=f'Generate a CRON expression for: {prompt}',
            system_prompt=SYSTEM_PROMPT,
            use_cache=True,
        )

        expression = result.content.strip()
        logger.info(f'GPT returned expression: {expression!r}')

        fields = _validate_and_parse(expression)
        description = get_description(expression)

        return CronGenerateResult(
            expression=expression,
            description=description,
            fields=fields,
            tokens_used=result.tokens,
        )
