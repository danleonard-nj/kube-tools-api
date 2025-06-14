import hashlib
import openai
from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration
from typing import List, Dict

from framework.logger import get_logger
from pydantic import BaseModel

from models.openai_config import OpenAIConfig

logger = get_logger(__name__)


def md5(text: str) -> str:
    """Generate an MD5 hash for the given text."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()


class CompletionResultModel(BaseModel):
    content: str
    tokens: int


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

    async def generate_completion(self, prompt: str, model: str = "gpt-4o-mini",
                                  temperature: float = 0.7, use_cache: bool = True,
                                  cache_ttl: int = 3600) -> CompletionResultModel:
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

        # Generate new response
        logger.info(f"Generating new response using {model}: {prompt[:25]}...")
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
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

    async def generate_response(
        self,
        input: str,
        model: str = "gpt-4o",
        tools: List[Dict] = None,
        temperature: float = 1.0,
        use_cache: bool = False,
        cache_ttl: int = 3600
    ) -> dict:
        """
        Generate a response with integrated tools via the responses.create endpoint.
        """
        tools = tools or []
        logger.info(f"Generating response using {model} with tools: {tools}")
        try:
            response = await self._client.responses.create(
                model=model,
                input=input,
                tools=tools,
                temperature=temperature
            )
            return response
        except Exception as e:
            logger.error(f"Error generating response with {model} and tools: {str(e)}")
            raise
