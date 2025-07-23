
import json
import os
from models.app_config import AppConfig


def load_config() -> AppConfig | None:
    if not os.path.exists('config.json'):
        raise FileNotFoundError('config.json file not found')

    with open('config.json', 'r') as file:
        return AppConfig.model_validate_json(file.read())


def load_action_types() -> dict:
    if not os.path.exists('./components/action_types.json'):
        raise FileNotFoundError('action_types.json file not found in components directory')

    with open('./components/action_types.json', 'r') as f:
        return json.load(f)
