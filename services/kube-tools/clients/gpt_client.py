import hashlib
import json
from enum import StrEnum
from typing import Dict, List, Literal, Optional, Union

from framework.clients.cache_client import CacheClientAsync
from framework.logger import get_logger
from openai import AsyncOpenAI
from pydantic import BaseModel

from domain.gpt import GPTModel
from models.openai_config import OpenAIConfig

logger = get_logger(__name__)


class ResponseResultModel(BaseModel):
    text: str
    usage: int
    data: dict


class CompletionResultModel(BaseModel):
    content: str
    tokens: int


class GptResponseToolType(StrEnum):
    WEB_SEARCH_PREVIEW = "web_search_preview"
    FILE_SEARCH = "file_search"
    COMPUTER_USE = "computer_use"
    CODE_INTERPRETER = "code_interpreter"
    RETRIEVAL = "retrieval"
    FUNCTION = "function"
    IMAGE_GENERATION = "image_generation"
    IMAGE_EDITING = "image_editing"
    TEXT_TO_SPEECH = "text_to_speech"
    TEXT_GENERATION = "text_generation"
    BROWSER = "browser"


class GPTClient:
    """Client for handling OpenAI GPT API interactions with caching support"""

    def __init__(
        self,
        config: OpenAIConfig,
        cache_client: CacheClientAsync,
        openai_client: AsyncOpenAI
    ):
        self._api_key = config.api_key
        self._cache_client = cache_client
        self._client = openai_client

    async def generate_completion(
        self,
        prompt: str,
        model: str = GPTModel.GPT_4O_MINI,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        use_cache: bool = True,
        cache_ttl: int = 3600,
        max_tokens: Optional[int] = None
    ) -> CompletionResultModel:
        """
        Generate a completion from the GPT model with optional caching
        Returns a CompletionResultModel.
        """

        # Check cache if available and enabled
        if use_cache and self._cache_client:
            cached_response = await self._get_cached_response(prompt, model)
            if cached_response:
                logger.info(f"Using cached response for {model} prompt")
                # If cached, we don't know token count, so set to 0 or estimate if needed
                return CompletionResultModel(content=cached_response, tokens=0)

        messages = [{
            'role': 'user',
            'content': prompt
        }]

        if system_prompt:
            messages.insert(0, {
                'role': 'system',
                'content': system_prompt
            })

        # Generate new response
        logger.info(f"Generating new response using {model}: {prompt[:25]}...")
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content.strip()
            tokens = response.usage.total_tokens if hasattr(response, 'usage') and response.usage else 0

            # Cache the response if caching is enabled
            if use_cache and self._cache_client:
                await self._cache_response(prompt, content, model, cache_ttl)

            return CompletionResultModel(content=content, tokens=tokens)
        except Exception as e:
            logger.error(f"Error generating completion with {model}: {str(e)}")
            raise

    async def generate_response(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: str = "gpt-4o",
        custom_tools: Optional[List[Dict[Literal['type'], GptResponseToolType]]] = None,
        temperature: float = 1.0,
        use_cache: bool = True,
        cache_ttl: int = 3600,
        max_output_tokens: Optional[int] = None
    ) -> ResponseResultModel:
        if use_cache and self._cache_client:
            cached = await self._get_cached_response(prompt, model)
            if cached:
                logger.info(f"Using cached response for {model} prompt")
                return ResponseResultModel.model_validate(cached)

        tools = custom_tools or []

        logger.info(f"Calling responses.create with model={model} and tools={tools}")
        try:
            response = await self._client.responses.create(
                model=model,
                input=prompt,
                instructions=system_prompt,
                tools=tools,
                temperature=temperature,
                max_output_tokens=max_output_tokens
            )

            result = ResponseResultModel(
                text=response.output_text,
                usage=response.usage.total_tokens if response.usage else 0,
                data=response.model_dump()
            )

            if use_cache and self._cache_client:
                await self._cache_response(prompt, result.model_dump(), model, cache_ttl)
            return result

        except Exception as e:
            logger.error(f"Error during responses.create: {str(e)}")
            raise

    async def generate_response_with_image_and_tools(
        self,
        image_bytes: str,
        prompt: str,
        system_prompt: str = None,
        model: str = "gpt-4o",
        temperature: float = 1.0,
        custom_tools: list = None,
        max_output_tokens: Optional[int] = None
    ) -> ResponseResultModel:
        """
        Send an image and prompt (with optional system prompt and tools) to GPT
        and return the response. `image_bytes` must be a data URL or image URL.
        """

        messages = [{
            'role': 'user',
            'content': [
                {'type': 'input_text', 'text': prompt},
                {'type': 'input_image', 'image_url': image_bytes}
            ]
        }]

        logger.info("Sending image, prompt, and tools to GPT")
        return await self.generate_response(
            model=model,
            prompt=messages,
            system_prompt=system_prompt,
            temperature=temperature,
            custom_tools=custom_tools,
            max_output_tokens=max_output_tokens
        )

    async def _get_cached_response(self, prompt: Union[str, List, Dict], model: str):
        """Get cached response for a prompt if available"""
        if not self._cache_client:
            return None

        cache_key = f"gpt_response:{model}:{self._prompt_hash(prompt)}"

        cached = await self._cache_client.get_json(cache_key)
        if cached and 'content' in cached:
            return cached['content']
        return None

    async def _cache_response(self, prompt: Union[str, List, Dict], data: dict, model: str, ttl: int):
        """Cache a response for future use"""
        if not self._cache_client:
            return

        cache_key = f"gpt_response:{model}:{self._prompt_hash(prompt)}"

        await self._cache_client.set_json(
            cache_key,
            data,
            ttl=ttl
        )

    @staticmethod
    def _prompt_hash(prompt: Union[str, List, Dict]) -> str:
        """Stable hash for a prompt, whether it's a string or a structured payload."""
        if not isinstance(prompt, str):
            prompt = json.dumps(prompt, sort_keys=True)
        return hashlib.sha256(prompt.encode('utf-8')).hexdigest()
