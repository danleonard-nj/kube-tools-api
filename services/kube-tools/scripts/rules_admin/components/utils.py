
import json
import os
from models.app_config import AppConfig
from logging import getLogger

logger = getLogger(__name__)


def load_config(env: str) -> AppConfig | None:

    filepath = 'config.dev.json' if env == 'local' else 'config.json'
    logger.info(f'Loading configuration from {filepath}')

    if not os.path.exists(filepath):
        raise FileNotFoundError(f'{filepath} file not found')

    with open(filepath, 'r') as file:
        return AppConfig.model_validate_json(file.read())


def load_action_types() -> dict:
    if not os.path.exists('./components/action_types.json'):
        raise FileNotFoundError('action_types.json file not found in components directory')

    with open('./components/action_types.json', 'r') as f:
        return json.load(f)
