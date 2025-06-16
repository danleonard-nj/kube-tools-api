from enum import Enum, StrEnum
import hashlib
import openai
from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration
from typing import Any, List, Dict, Literal, Optional, Union

from framework.logger import get_logger
from pydantic import BaseModel

from domain.gpt import GPTModel
from models.openai_config import OpenAIConfig
from openai.types.responses import ResponseIncludable

logger = get_logger(__name__)


def md5(text: str) -> str:
    """Generate an MD5 hash for the given text."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()


class CompletionResultModel(BaseModel):
    content: str
    tokens: int


class ToolOutputAnnotation(BaseModel):
    type: str
    start_index: int
    end_index: int
    url: str
    title: Optional[str] = None


class ToolOutputContent(BaseModel):
    type: str
    text: Optional[str] = None
    annotations: Optional[List[ToolOutputAnnotation]] = None


class AssistantMessage(BaseModel):
    id: str
    type: Literal["message"]
    role: str
    status: str
    content: List[ToolOutputContent]


class ToolCall(BaseModel):
    id: str
    type: str
    status: str


ResponseOutput = Union[AssistantMessage, ToolCall]


class ResponsesAPIResult(BaseModel):
    id: str
    model: str
    status: str
    output: List[ResponseOutput]
    usage: Optional[Dict[str, Any]] = None
    created_at: Optional[float] = None
    tools: Optional[List[Dict[str, Any]]] = None


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

    def __init__(self, config: OpenAIConfig,
                 cache_client: CacheClientAsync = None):
        """
        Initialize the GPT client

        Args:
            api_key: OpenAI API key
            cache_client: Optional cache client for caching responses
        """
        self._api_key = config.api_key
        self._cache_client = cache_client
        self._client = openai.AsyncOpenAI(api_key=self._api_key)

        self.count = 0

    async def generate_completion(
        self,
        prompt: str,
        model: str = GPTModel.GPT_4O_MINI,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        use_cache: bool = True,
        cache_ttl: int = 3600
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
                temperature=temperature
            )
            content = response.choices[0].message.content.strip()
            tokens = response.usage.total_tokens if hasattr(response, 'usage') and response.usage else 0

            # Cache the response if caching is enabled
            if use_cache and self._cache_client:
                await self._cache_response(prompt, content, model, cache_ttl)

            with open(f'./prompts/response_{md5(prompt)}.txt', 'w', encoding='utf-8') as f:
                f.write(content)
            self.count += 1

            return CompletionResultModel(content=content, tokens=tokens)
        except Exception as e:
            logger.error(f"Error generating completion with {model}: {str(e)}")
            raise

    async def generate_response(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: str = "gpt-4o",
        use_all_tools: bool = False,
        custom_tools: Optional[List[Dict[Literal['type'], GptResponseToolType]]] = None,
        temperature: float = 1.0,
        use_cache: bool = False,
        cache_ttl: int = 3600
    ) -> ResponsesAPIResult:
        if use_cache and self._cache_client:
            cached = await self._get_cached_response(input, model)
            if cached:
                logger.info(f"Using cached response for {model} input")
                return ResponsesAPIResult.model_validate(cached)

        tools = custom_tools or []

        if use_all_tools:
            tools = [
                {"type": GptResponseToolType.WEB_SEARCH_PREVIEW},
                {"type": GptResponseToolType.FILE_SEARCH},
                {"type": GptResponseToolType.COMPUTER_USE},
                {"type": GptResponseToolType.CODE_INTERPRETER},
                {"type": GptResponseToolType.RETRIEVAL},
                {"type": GptResponseToolType.FUNCTION},
                {"type": GptResponseToolType.IMAGE_GENERATION},
                {"type": GptResponseToolType.IMAGE_EDITING},
                {"type": GptResponseToolType.TEXT_TO_SPEECH},
                {"type": GptResponseToolType.TEXT_GENERATION},
                {"type": GptResponseToolType.BROWSER}
            ]

        logger.info(f"Calling responses.create with tools={tools}")
        try:
            response = await self._client.responses.create(
                model=model,
                input=prompt,
                instructions=system_prompt,
                tools=tools,
                temperature=temperature
            )

            parsed = response.model_dump()

            if use_cache and self._cache_client:
                await self._cache_response(input, parsed, model, cache_ttl)

            return ResponsesAPIResult.model_validate(parsed)
        except Exception as e:
            logger.error(f"Error during responses.create: {str(e)}")
            raise

    async def generate_response_with_image(self, image_bytes: bytes, prompt: str, model: str = "gpt-4o", temperature: float = 1.0) -> str:
        """
        Send an image and prompt to GPT and return the response content as string.
        """
        # This is a placeholder. Actual implementation depends on OpenAI API support for image input.
        # For now, assume we can send image as base64 or bytes in the prompt or as a separate parameter.
        import base64
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        messages = [
            {'role': 'user', 'content': prompt},
            {'role': 'user', 'content': {'type': 'image', 'data': image_b64}}
        ]
        logger.info(f"Sending image and prompt to GPT: {prompt[:25]}...")
        response = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature
        )
        content = response.choices[0].message.content.strip()
        return content

    async def generate_response_with_image_and_tools(self, image_bytes: str, prompt: str, system_prompt: str = None, model: str = "gpt-4o", temperature: float = 1.0, custom_tools: list = None) -> str:
        """
        Send an image and prompt (with optional system prompt and tools) to GPT and return the response content as string.
        Detects image type for correct MIME.
        Only includes tools if a valid function tool is provided.
        """

        messages = []
        if system_prompt:
            messages.append({'role': 'system', 'content': system_prompt})
        messages.append({
            'role': 'user',
            'content': [
                {'type': 'text', 'text': prompt},
                {'type': 'image_url', 'image_url': {'url': image_bytes}}
            ]
        })
        logger.info(f"Sending image, prompt, and tools to GPT")
        kwargs = dict(model=model, messages=messages, temperature=temperature)
        # Only include tools if a valid function tool is provided
        if custom_tools and any('function' in t for t in custom_tools):
            kwargs['tools'] = custom_tools
        response = await self._client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content.strip()
        return content

    async def _get_cached_response(self, prompt: str, model: str):
        """Get cached response for a prompt if available"""
        if not self._cache_client:
            return None

        prompt_hash = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
        cache_key = f"gpt_response:{model}:{prompt_hash}"

        cached = await self._cache_client.get_json(cache_key)
        if cached and 'content' in cached:
            return cached['content']
        return None

    async def _cache_response(self, prompt: str, response: str, model: str, ttl: int):
        """Cache a response for future use"""
        if not self._cache_client:
            return

        prompt_hash = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
        cache_key = f"gpt_response:{model}:{prompt_hash}"

        await self._cache_client.set_json(
            cache_key,
            {'content': response},
            ttl=ttl
        )
