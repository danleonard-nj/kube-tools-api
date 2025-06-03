import hashlib
import logging
import openai
from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration

from framework.logger import get_logger

logger = get_logger(__name__)


class GPTClient:
    """Client for handling OpenAI GPT API interactions with caching support"""

    def __init__(self, configuration: Configuration,
                 cache_client: CacheClientAsync = None):
        """
        Initialize the GPT client

        Args:
            api_key: OpenAI API key
            cache_client: Optional cache client for caching responses
        """
        self._api_key = configuration.openai.get('api_key')
        self._cache_client = cache_client
        self._client = openai.AsyncOpenAI(api_key=self._api_key)

    async def generate_completion(self, prompt: str, model: str = "gpt-4o-mini",
                                  temperature: float = 0.7, use_cache: bool = True,
                                  cache_ttl: int = 3600):
        """
        Generate a completion from the GPT model with optional caching

        Args:
            prompt: The prompt to send to the model
            model: The model to use (default: gpt-3.5-turbo)
            temperature: Temperature parameter (default: 0.7)
            use_cache: Whether to use caching (default: True)
            cache_ttl: Time to live for cached responses in seconds (default: 1 hour)

        Returns:
            The generated text
        """
        # Check cache if available and enabled
        if use_cache and self._cache_client:
            cached_response = await self._get_cached_response(prompt, model)
            if cached_response:
                logger.info(f"Using cached response for {model} prompt")
                return cached_response

        # Generate new response
        logger.info(f"Generating new response using {model}")
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature
            )
            content = response.choices[0].message.content.strip()

            # Cache the response if caching is enabled
            if use_cache and self._cache_client:
                await self._cache_response(prompt, content, model, cache_ttl)

            return content
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
