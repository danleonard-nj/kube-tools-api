import hashlib
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

from anthropic import AsyncAnthropic
from google import genai
from google.genai import types as genai_types
from openai import AsyncOpenAI

from framework.clients.cache_client import CacheClientAsync
from services.llm.llm_output import (
    OutputType,
    StructuredOutputError,
    is_loose_json,
    is_pydantic_model,
    normalize_output_type,
    parse_text_to_output_type,
    parse_value_to_output_type,
    pydantic_to_openai_strict_schema,
    schema_fingerprint,
)
from models.anthropic_config import AnthropicConfig
from models.google_config import GoogleConfig
from models.openai_config import OpenAIConfig

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TTL_SECONDS = 60 * 60  # 1 hour
DEFAULT_AGENT_MAX_TURNS = 10

# Re-export for convenience so callers can `from services.llm.llm_provider import StructuredOutputError`
__all__ = [
    "LLMProvider",
    "ChatGPTProvider",
    "AnthropicLLMProvider",
    "GoogleLLMProvider",
    "StructuredOutputError",
]

# A tool executor is an async callable: (name, arguments_dict) -> result.
# Result can be anything JSON-serializable; we'll stringify it for the model.
ToolExecutor = Callable[[str, dict], Awaitable[Any]]

# Internal sentinel name for the Anthropic structured-output tool.
_ANTHROPIC_STRUCTURED_TOOL_NAME = "_structured_output"


class LLMProvider(ABC):
    """
    Base interface for LLM providers.

    Tool definitions are passed through to the underlying SDK as-is.
    Each provider documents its native tool format below — there is no
    cross-provider abstraction layer for tools. If you need to call
    multiple providers with the same tool, define it in each format.

    Caching: when use_cache=True, the full request including tools is
    hashed and cached. Callers should opt out (use_cache=False) for
    tool-using agent loops where intermediate turns shouldn't be cached
    individually.
    """

    PROVIDER_NAME: str = "base"

    def __init__(self, cache_client: CacheClientAsync):
        self._cache_client = cache_client

    # --- public API ------------------------------------------------------

    async def generate_response(
        self,
        prompt: str,
        model: str,
        system_prompt: str = "",
        use_cache: bool = False,
        output_type: OutputType | None = None,
        **kwargs,
    ) -> dict:
        """
        Single-turn generation. If the model returns tool calls, they are
        included in the response dict under `tool_calls` — the caller is
        responsible for executing them and continuing the conversation
        (or use `generate_with_tools` for an automated loop).

        If `output_type` is provided, the model is constrained to produce
        JSON matching the type, and the parsed result is returned in the
        `parsed` field of the response dict. Raises StructuredOutputError
        if parsing fails.
        """
        output_type = normalize_output_type(output_type)

        if use_cache:
            cache_key = self._build_cache_key(
                prompt=prompt,
                model=model,
                system_prompt=system_prompt,
                output_type=output_type,
                kwargs=kwargs,
            )

            cached = await self._get_cached(cache_key)
            if cached is not None:
                logger.debug(
                    "Cache hit for provider=%s model=%s key=%s",
                    self.PROVIDER_NAME, model, cache_key,
                )
                # Re-parse from cached text since `parsed` isn't cached
                # (Pydantic instances aren't directly JSON-serializable).
                if output_type is not None and cached.get("parsed") is None:
                    cached["parsed"] = parse_text_to_output_type(
                        cached.get("text", ""), output_type
                    )
                return cached

            response = await self._generate(
                prompt=prompt,
                model=model,
                system_prompt=system_prompt,
                output_type=output_type,
                **kwargs,
            )

            ttl = kwargs.get("cache_ttl_seconds", DEFAULT_CACHE_TTL_SECONDS)
            await self._set_cached(cache_key, response, ttl=ttl)
            return response

        return await self._generate(
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            output_type=output_type,
            **kwargs,
        )

    async def generate_with_tools(
        self,
        prompt: str,
        model: str,
        tools: list,
        tool_executor: ToolExecutor,
        system_prompt: str = "",
        max_turns: int = DEFAULT_AGENT_MAX_TURNS,
        use_cache: bool = False,
        output_type: OutputType | None = None,
        **kwargs,
    ) -> dict:
        """
        Multi-turn agent loop: calls the model with tools, executes any
        tool calls via `tool_executor`, feeds results back, repeats until
        the model returns a final answer or `max_turns` is reached.

        If `output_type` is provided, the model's FINAL answer (after all
        tool use) is constrained to JSON matching the type. Parsed result
        is in the `parsed` field. Raises StructuredOutputError on failure.
        """
        output_type = normalize_output_type(output_type)
        return await self._run_tool_loop(
            prompt=prompt,
            model=model,
            tools=tools,
            tool_executor=tool_executor,
            system_prompt=system_prompt,
            max_turns=max_turns,
            use_cache=use_cache,
            output_type=output_type,
            **kwargs,
        )

    # --- abstract hooks --------------------------------------------------

    @abstractmethod
    async def _generate(
        self,
        prompt: str,
        model: str,
        system_prompt: str,
        output_type: OutputType | None = None,
        **kwargs,
    ) -> dict:
        ...

    @abstractmethod
    async def _run_tool_loop(
        self,
        prompt: str,
        model: str,
        tools: list,
        tool_executor: ToolExecutor,
        system_prompt: str,
        max_turns: int,
        use_cache: bool,
        output_type: OutputType | None = None,
        **kwargs,
    ) -> dict:
        ...

    # --- caching helpers -------------------------------------------------

    def _build_cache_key(
        self,
        prompt: str,
        model: str,
        system_prompt: str,
        kwargs: dict,
        output_type: Any = None,
    ) -> str:
        # Strip non-request kwargs before hashing.
        hashable_kwargs = {
            k: v for k, v in kwargs.items()
            if k not in ("cache_ttl_seconds",)
        }

        payload = json.dumps(
            {
                "provider": self.PROVIDER_NAME,
                "model": model,
                "system_prompt": system_prompt,
                "prompt": prompt,
                "kwargs": hashable_kwargs,
                "output_type": schema_fingerprint(output_type),
            },
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"llm:{self.PROVIDER_NAME}:{digest}"

    async def _get_cached(self, key: str) -> dict | None:
        try:
            raw = await self._cache_client.get_cache(key)
        except Exception:
            logger.exception("Cache read failed for key=%s", key)
            return None

        if raw is None:
            return None

        if isinstance(raw, dict):
            return raw

        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            logger.warning("Cached value for key=%s was not JSON-decodable", key)
            return None

    async def _set_cached(self, key: str, value: dict, ttl: int) -> None:
        try:
            # Strip `raw` (provider-native, not JSON-serializable) and
            # `parsed` (Pydantic instances aren't directly serializable;
            # we re-parse from `text` on cache read).
            cacheable = {
                k: v for k, v in value.items()
                if k not in ("raw", "parsed")
            }
            await self._cache_client.set_cache(
                key=key,
                value=json.dumps(cacheable, default=str),
                ttl=ttl,
            )
        except Exception:
            logger.exception("Cache write failed for key=%s", key)

    # --- response normalization ------------------------------------------

    @staticmethod
    def _normalized_response(
        text: str,
        model: str,
        provider: str,
        finish_reason: str | None,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        tool_calls: list | None = None,
        raw: Any | None = None,
        parsed: Any = None,
    ) -> dict:
        return {
            "text": text,
            "model": model,
            "provider": provider,
            "finish_reason": finish_reason,
            "tool_calls": tool_calls or [],
            "parsed": parsed,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": (
                    (prompt_tokens or 0) + (completion_tokens or 0)
                    if prompt_tokens is not None or completion_tokens is not None
                    else None
                ),
            },
            "raw": raw,
        }


# =============================================================================
# OpenAI (Responses API)
# =============================================================================


class ChatGPTProvider(LLMProvider):
    """
    OpenAI provider using the Responses API (client.responses.create).

    Tool format (pass-through):
        Function tools:
            {
                "type": "function",
                "name": "get_weather",
                "description": "...",
                "parameters": { ...JSON schema... },
                "strict": True,
            }
        Hosted tools (executed server-side, no executor needed):
            {"type": "web_search"}
            {"type": "file_search", "vector_store_ids": [...]}
            {"type": "code_interpreter", "container": {"type": "auto"}}

    Reasoning items in `output` are preserved across tool-loop turns —
    required for o-series and gpt-5 models to maintain chain-of-thought
    state. We pass the full prior `output` back as input on each turn.
    """

    PROVIDER_NAME = "openai"

    # Kwargs that are valid Responses API request params; everything else
    # is dropped to avoid passing unexpected fields to the SDK.
    _PASSTHROUGH_KWARGS = frozenset({
        "temperature", "top_p", "max_output_tokens", "reasoning",
        "text", "tool_choice", "parallel_tool_calls", "metadata",
        "store", "previous_response_id", "truncation", "user",
    })

    def __init__(
        self,
        config: OpenAIConfig,
        cache_client: CacheClientAsync,
        openai_client: AsyncOpenAI,
    ):
        super().__init__(cache_client=cache_client)
        self._config = config
        self._client = openai_client

    async def _generate(
        self,
        prompt: str,
        model: str,
        system_prompt: str,
        output_type: OutputType | None = None,
        **kwargs,
    ) -> dict:
        kwargs = self._inject_text_format(output_type, kwargs)
        request = self._build_request(
            input_=prompt,
            model=model,
            system_prompt=system_prompt,
            kwargs=kwargs,
        )
        response = await self._client.responses.create(**request)
        return self._parse_response(response, output_type=output_type)

    async def _run_tool_loop(
        self,
        prompt: str,
        model: str,
        tools: list,
        tool_executor: ToolExecutor,
        system_prompt: str,
        max_turns: int,
        use_cache: bool,
        output_type: OutputType | None = None,
        **kwargs,
    ) -> dict:
        # Responses API conversation state: list of input items. We start
        # with the user message and append the model's `output` items plus
        # our `function_call_output` items each turn.
        conversation: list[dict] = [
            {"role": "user", "content": prompt},
        ]

        kwargs = {**kwargs, "tools": tools}
        # Apply text.format to every turn — the structured output constraint
        # holds across the whole loop. The model only emits a structured
        # answer when it stops calling tools.
        kwargs = self._inject_text_format(output_type, kwargs)
        last_response = None

        for turn in range(max_turns):
            request = self._build_request(
                input_=conversation,
                model=model,
                system_prompt=system_prompt,
                kwargs=kwargs,
            )
            response = await self._client.responses.create(**request)
            last_response = response

            tool_calls = self._extract_tool_calls(response)

            if not tool_calls:
                # Model produced a final answer.
                return self._parse_response(response, output_type=output_type)

            # Append the entire prior output (reasoning + function_calls)
            # to the conversation. Required for reasoning models.
            for item in response.output:
                conversation.append(self._serialize_output_item(item))

            # Execute each tool call and append its output.
            for call in tool_calls:
                try:
                    result = await tool_executor(call["name"], call["arguments"])
                    output_str = (
                        result if isinstance(result, str)
                        else json.dumps(result, default=str)
                    )
                except Exception as e:
                    logger.exception(
                        "Tool executor failed for tool=%s", call["name"]
                    )
                    output_str = json.dumps({"error": str(e)})

                conversation.append({
                    "type": "function_call_output",
                    "call_id": call["id"],
                    "output": output_str,
                })

        logger.warning(
            "Tool loop hit max_turns=%d without final answer", max_turns
        )
        return self._parse_response(last_response, output_type=output_type) if last_response else (
            self._normalized_response(
                text="", model=model, provider=self.PROVIDER_NAME,
                finish_reason="max_turns_exceeded",
                prompt_tokens=None, completion_tokens=None,
            )
        )

    @staticmethod
    def _inject_text_format(output_type: Any, kwargs: dict) -> dict:
        """
        Translate output_type into Responses API `text.format`.

        - Pydantic model -> json_schema with strict=True
        - dict / 'json'  -> json_object (no schema enforcement)

        Caller-provided `text` kwarg wins; we don't override an explicit
        text.format setting.
        """
        if output_type is None:
            return kwargs
        if "text" in kwargs and isinstance(kwargs["text"], dict) and "format" in kwargs["text"]:
            return kwargs

        if is_pydantic_model(output_type):
            schema = pydantic_to_openai_strict_schema(output_type)
            text_format = {
                "type": "json_schema",
                "name": output_type.__name__,
                "schema": schema,
                "strict": True,
            }
        elif is_loose_json(output_type):
            text_format = {"type": "json_object"}
        else:
            return kwargs

        kwargs = {**kwargs}
        kwargs["text"] = {**kwargs.get("text", {}), "format": text_format}
        return kwargs

    # --- request building -----------------------------------------------

    def _build_request(
        self,
        input_,
        model: str,
        system_prompt: str,
        kwargs: dict,
    ) -> dict:
        request: dict[str, Any] = {
            "model": model,
            "input": input_,
        }
        if system_prompt:
            request["instructions"] = system_prompt

        if "tools" in kwargs:
            request["tools"] = kwargs["tools"]

        for k in self._PASSTHROUGH_KWARGS:
            if k in kwargs:
                request[k] = kwargs[k]

        return request

    # --- response parsing -----------------------------------------------

    def _parse_response(self, response, output_type: Any = None) -> dict:
        # `output_text` concatenates all output_text content from message
        # items. Empty if the response only contains tool calls.
        text = getattr(response, "output_text", "") or ""

        tool_calls = self._extract_tool_calls(response)

        if tool_calls:
            finish_reason = "tool_calls"
        else:
            finish_reason = getattr(response, "status", None)

        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "input_tokens", None) if usage else None
        completion_tokens = getattr(usage, "output_tokens", None) if usage else None

        # Only attempt parsing when there's a final text answer (no tool
        # calls outstanding) AND the caller asked for a structured output.
        parsed = None
        if output_type is not None and not tool_calls:
            parsed = parse_text_to_output_type(text, output_type)

        return self._normalized_response(
            text=text,
            model=getattr(response, "model", ""),
            provider=self.PROVIDER_NAME,
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            tool_calls=tool_calls,
            raw=response,
            parsed=parsed,
        )

    @staticmethod
    def _extract_tool_calls(response) -> list[dict]:
        calls: list[dict] = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) == "function_call":
                args_raw = getattr(item, "arguments", "{}")
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                except json.JSONDecodeError:
                    args = {"_raw": args_raw}

                calls.append({
                    "id": getattr(item, "call_id", None),
                    "name": getattr(item, "name", ""),
                    "arguments": args,
                })
        return calls

    @staticmethod
    def _serialize_output_item(item) -> dict:
        # Pydantic model_dump produces a JSON-shaped object the API will
        # accept as an input item on the next turn.
        if hasattr(item, "model_dump"):
            return item.model_dump(exclude_none=True)
        if hasattr(item, "dict"):
            return item.dict(exclude_none=True)
        return dict(item)


# =============================================================================
# Anthropic
# =============================================================================


class AnthropicLLMProvider(LLMProvider):
    """
    Anthropic provider using messages.create.

    Tool format (pass-through):
        {
            "name": "get_weather",
            "description": "...",
            "input_schema": { ...JSON schema... }
        }

    Note: `system` is a top-level param, NOT a message in the array.
    `max_tokens` is required by the API; defaults to 4096 if not provided.
    """

    PROVIDER_NAME = "anthropic"
    DEFAULT_MAX_TOKENS = 4096

    _PASSTHROUGH_KWARGS = frozenset({
        "temperature", "top_p", "top_k", "stop_sequences",
        "tool_choice", "metadata",
    })

    def __init__(
        self,
        config: AnthropicConfig,
        cache_client: CacheClientAsync,
        anthropic_client: AsyncAnthropic,
    ):
        super().__init__(cache_client=cache_client)
        self._config = config
        self._client = anthropic_client

    async def _generate(
        self,
        prompt: str,
        model: str,
        system_prompt: str,
        output_type: OutputType | None = None,
        **kwargs,
    ) -> dict:
        kwargs = self._inject_structured_output_tool(output_type, kwargs)
        request = self._build_request(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            system_prompt=system_prompt,
            kwargs=kwargs,
        )
        message = await self._client.messages.create(**request)
        return self._parse_response(message, output_type=output_type)

    async def _run_tool_loop(
        self,
        prompt: str,
        model: str,
        tools: list,
        tool_executor: ToolExecutor,
        system_prompt: str,
        max_turns: int,
        use_cache: bool,
        output_type: OutputType | None = None,
        **kwargs,
    ) -> dict:
        # Anthropic structured output uses the tool-call trick. When tools
        # AND output_type are both requested, we add the structured-output
        # tool to the tools list. The model will call user tools as needed,
        # and call the structured-output tool when ready to give a final
        # answer. We detect that and return the parsed input.
        effective_tools = list(tools)
        if output_type is not None:
            effective_tools = effective_tools + [
                self._build_structured_output_tool(output_type)
            ]

        messages: list[dict] = [{"role": "user", "content": prompt}]
        kwargs = {**kwargs, "tools": effective_tools}
        last_message = None

        for turn in range(max_turns):
            request = self._build_request(
                messages=messages,
                model=model,
                system_prompt=system_prompt,
                kwargs=kwargs,
            )
            message = await self._client.messages.create(**request)
            last_message = message

            # Check if the model called the structured-output tool — that's
            # our signal it's done.
            structured_call = self._find_structured_output_call(
                message, output_type
            )
            if structured_call is not None:
                return self._parse_response(
                    message, output_type=output_type,
                    structured_call=structured_call,
                )

            if message.stop_reason != "tool_use":
                # Final answer with no structured output tool call.
                return self._parse_response(message, output_type=output_type)

            # Append assistant message with full content blocks verbatim.
            messages.append({
                "role": "assistant",
                "content": [
                    block.model_dump(exclude_none=True)
                    if hasattr(block, "model_dump") else dict(block)
                    for block in message.content
                ],
            })

            # Execute user tool_use blocks (skip the structured-output tool
            # if for some reason it appears here — handled above).
            tool_results = []
            for block in message.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                if block.name == _ANTHROPIC_STRUCTURED_TOOL_NAME:
                    continue
                try:
                    result = await tool_executor(block.name, block.input)
                    content_str = (
                        result if isinstance(result, str)
                        else json.dumps(result, default=str)
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content_str,
                    })
                except Exception as e:
                    logger.exception(
                        "Tool executor failed for tool=%s", block.name
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps({"error": str(e)}),
                        "is_error": True,
                    })

            messages.append({"role": "user", "content": tool_results})

        logger.warning(
            "Tool loop hit max_turns=%d without final answer", max_turns
        )
        return self._parse_response(last_message, output_type=output_type) if last_message else (
            self._normalized_response(
                text="", model=model, provider=self.PROVIDER_NAME,
                finish_reason="max_turns_exceeded",
                prompt_tokens=None, completion_tokens=None,
            )
        )

    # --- structured output via tool-call trick -------------------------

    @staticmethod
    def _build_structured_output_tool(output_type: Any) -> dict:
        """
        Build a synthetic tool whose input_schema IS the desired output schema.
        The model 'calls' this tool to deliver the structured result.
        """
        if is_pydantic_model(output_type):
            schema = output_type.model_json_schema()
            description = (
                f"Return the final answer in this format. "
                f"You MUST call this tool to provide your final response."
            )
        elif is_loose_json(output_type):
            schema = {
                "type": "object",
                "additionalProperties": True,
            }
            description = (
                "Return the final answer as a JSON object. "
                "You MUST call this tool to provide your final response."
            )
        else:
            raise ValueError(f"Unsupported output_type: {output_type!r}")

        return {
            "name": _ANTHROPIC_STRUCTURED_TOOL_NAME,
            "description": description,
            "input_schema": schema,
        }

    def _inject_structured_output_tool(
        self, output_type: Any, kwargs: dict
    ) -> dict:
        """
        For single-turn _generate: replace tools with just the structured
        output tool and force the model to call it.

        Note: this hijacks the tools field. If the caller passed their own
        tools to _generate (without using generate_with_tools), they will
        be overridden. For tool use + structured output, callers should
        use generate_with_tools.
        """
        if output_type is None:
            return kwargs

        kwargs = {**kwargs}
        if "tools" in kwargs and kwargs["tools"]:
            logger.warning(
                "Anthropic structured output replaces user-supplied tools "
                "in single-turn calls. Use generate_with_tools to combine."
            )

        kwargs["tools"] = [self._build_structured_output_tool(output_type)]
        kwargs["tool_choice"] = {
            "type": "tool",
            "name": _ANTHROPIC_STRUCTURED_TOOL_NAME,
        }
        return kwargs

    @staticmethod
    def _find_structured_output_call(message, output_type: Any):
        """
        Scan the message content for a tool_use block that matches our
        synthetic structured-output tool. Returns the block, or None.
        """
        if output_type is None:
            return None
        for block in message.content:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == _ANTHROPIC_STRUCTURED_TOOL_NAME
            ):
                return block
        return None

    def _build_request(
        self,
        messages: list,
        model: str,
        system_prompt: str,
        kwargs: dict,
    ) -> dict:
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": kwargs.get("max_tokens", self.DEFAULT_MAX_TOKENS),
            "messages": messages,
        }
        if system_prompt:
            request["system"] = system_prompt

        if "tools" in kwargs:
            request["tools"] = kwargs["tools"]

        for k in self._PASSTHROUGH_KWARGS:
            if k in kwargs:
                request[k] = kwargs[k]

        return request

    def _parse_response(
        self,
        message,
        output_type: Any = None,
        structured_call: Any = None,
    ) -> dict:
        text_parts = []
        tool_calls = []

        # If output_type was requested, scan for the structured-output tool
        # call ourselves so single-turn _generate works without a loop.
        if output_type is not None and structured_call is None:
            structured_call = self._find_structured_output_call(
                message, output_type
            )

        for block in message.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                # Hide the synthetic structured-output tool from the caller.
                if block.name == _ANTHROPIC_STRUCTURED_TOOL_NAME:
                    continue
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input,
                })

        usage = getattr(message, "usage", None)

        parsed = None
        text_out = "".join(text_parts)
        if structured_call is not None:
            # `input` is already a dict — go through value parser.
            parsed = parse_value_to_output_type(
                structured_call.input, output_type
            )
            # Surface the structured payload as text too, for callers that
            # only look at `text`.
            text_out = json.dumps(structured_call.input, default=str)

        return self._normalized_response(
            text=text_out,
            model=message.model,
            provider=self.PROVIDER_NAME,
            finish_reason=message.stop_reason,
            prompt_tokens=getattr(usage, "input_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "output_tokens", None) if usage else None,
            tool_calls=tool_calls,
            raw=message,
            parsed=parsed,
        )


# =============================================================================
# Google (Gemini via google-genai)
# =============================================================================


class GoogleLLMProvider(LLMProvider):
    """
    Google provider using google-genai (genai.Client).

    Tool format (pass-through):
        Function declarations:
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name="get_weather",
                    description="...",
                    parameters=genai_types.Schema(...),
                ),
            ])
        Or as a dict that will be coerced by the SDK:
            {"function_declarations": [{"name": "...", "parameters": {...}}]}

    Tools are passed through as-is into GenerateContentConfig.
    """

    PROVIDER_NAME = "google"

    def __init__(
        self,
        config: GoogleConfig,
        cache_client: CacheClientAsync,
        google_client: genai.Client,
    ):
        super().__init__(cache_client=cache_client)
        self._config = config
        self._client = google_client

    async def _generate(
        self,
        prompt: str,
        model: str,
        system_prompt: str,
        output_type: OutputType | None = None,
        **kwargs,
    ) -> dict:
        kwargs = self._inject_response_schema(output_type, kwargs)
        config = self._build_config(system_prompt=system_prompt, kwargs=kwargs)
        response = await self._client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        return self._parse_response(response, model=model, output_type=output_type)

    async def _run_tool_loop(
        self,
        prompt: str,
        model: str,
        tools: list,
        tool_executor: ToolExecutor,
        system_prompt: str,
        max_turns: int,
        use_cache: bool,
        output_type: OutputType | None = None,
        **kwargs,
    ) -> dict:
        contents: list = [
            genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=prompt)],
            ),
        ]
        kwargs = {**kwargs, "tools": tools}
        # NOTE: Gemini doesn't allow combining function-calling tools with
        # response_schema in the same request. When output_type is set with
        # tools, we let the loop run with tools enabled, and apply the
        # schema only on the final turn (after tool calls finish). We
        # detect "final turn" as one where no function_call parts come back.
        last_response = None

        for turn in range(max_turns):
            # On any turn except a "final answer" retry, keep tools active
            # and don't constrain the schema (Gemini rejects the combo).
            turn_kwargs = kwargs
            config = self._build_config(
                system_prompt=system_prompt, kwargs=turn_kwargs,
            )
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            last_response = response

            function_calls = self._extract_function_calls(response)
            if not function_calls:
                # If no tool calls AND output_type requested, re-issue the
                # final turn with response_schema active so we get a
                # validated structured answer.
                if output_type is not None:
                    final_kwargs = {
                        k: v for k, v in kwargs.items() if k != "tools"
                    }
                    final_kwargs = self._inject_response_schema(
                        output_type, final_kwargs
                    )
                    final_config = self._build_config(
                        system_prompt=system_prompt, kwargs=final_kwargs,
                    )
                    final_response = await self._client.aio.models.generate_content(
                        model=model,
                        contents=contents,
                        config=final_config,
                    )
                    return self._parse_response(
                        final_response, model=model, output_type=output_type,
                    )
                return self._parse_response(response, model=model, output_type=None)

            # Append the model's response content (with function_call parts).
            if response.candidates and response.candidates[0].content:
                contents.append(response.candidates[0].content)

            # Build a single user-role Content with function_response Parts.
            response_parts = []
            for fc in function_calls:
                try:
                    result = await tool_executor(fc["name"], fc["arguments"])
                    if not isinstance(result, dict):
                        result = {"result": result}
                except Exception as e:
                    logger.exception(
                        "Tool executor failed for tool=%s", fc["name"]
                    )
                    result = {"error": str(e)}

                response_parts.append(
                    genai_types.Part.from_function_response(
                        name=fc["name"],
                        response=result,
                    )
                )

            contents.append(
                genai_types.Content(role="user", parts=response_parts)
            )

        logger.warning(
            "Tool loop hit max_turns=%d without final answer", max_turns
        )
        return self._parse_response(last_response, model=model, output_type=output_type) if last_response else (
            self._normalized_response(
                text="", model=model, provider=self.PROVIDER_NAME,
                finish_reason="max_turns_exceeded",
                prompt_tokens=None, completion_tokens=None,
            )
        )

    @staticmethod
    def _inject_response_schema(output_type: Any, kwargs: dict) -> dict:
        """
        Translate output_type into Gemini's response_mime_type + response_schema.
        Pydantic models are passed directly — google-genai handles the conversion.
        For loose JSON, only response_mime_type is set.
        """
        if output_type is None:
            return kwargs
        kwargs = {**kwargs}
        kwargs["response_mime_type"] = "application/json"
        if is_pydantic_model(output_type):
            kwargs["response_schema"] = output_type
        # For loose JSON we only set the mime type; no schema.
        return kwargs

    def _build_config(
        self,
        system_prompt: str,
        kwargs: dict,
    ) -> genai_types.GenerateContentConfig | None:
        config_kwargs: dict[str, Any] = {}
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt
        if "temperature" in kwargs:
            config_kwargs["temperature"] = kwargs["temperature"]
        if "top_p" in kwargs:
            config_kwargs["top_p"] = kwargs["top_p"]
        if "top_k" in kwargs:
            config_kwargs["top_k"] = kwargs["top_k"]
        if "max_tokens" in kwargs:
            config_kwargs["max_output_tokens"] = kwargs["max_tokens"]
        if "stop" in kwargs:
            config_kwargs["stop_sequences"] = (
                kwargs["stop"] if isinstance(kwargs["stop"], list) else [kwargs["stop"]]
            )
        if "tools" in kwargs:
            config_kwargs["tools"] = kwargs["tools"]
        if "tool_config" in kwargs:
            config_kwargs["tool_config"] = kwargs["tool_config"]
        if "response_mime_type" in kwargs:
            config_kwargs["response_mime_type"] = kwargs["response_mime_type"]
        if "response_schema" in kwargs:
            config_kwargs["response_schema"] = kwargs["response_schema"]

        return (
            genai_types.GenerateContentConfig(**config_kwargs)
            if config_kwargs else None
        )

    @staticmethod
    def _extract_function_calls(response) -> list[dict]:
        calls = []
        if not response.candidates:
            return calls
        content = response.candidates[0].content
        if not content or not content.parts:
            return calls
        for part in content.parts:
            fc = getattr(part, "function_call", None)
            if fc and fc.name:
                # `args` is a proto Struct; coerce to plain dict.
                args = dict(fc.args) if fc.args else {}
                calls.append({
                    "id": fc.name,  # Gemini doesn't supply a separate call id
                    "name": fc.name,
                    "arguments": args,
                })
        return calls

    def _parse_response(self, response, model: str, output_type: Any = None) -> dict:
        text = response.text or ""
        tool_calls = self._extract_function_calls(response)

        finish_reason = None
        if response.candidates:
            fr = getattr(response.candidates[0], "finish_reason", None)
            if fr is not None:
                finish_reason = str(fr)

        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = getattr(usage, "prompt_token_count", None) if usage else None
        completion_tokens = getattr(usage, "candidates_token_count", None) if usage else None

        # Prefer the SDK's pre-parsed value when present (Pydantic models
        # via response_schema), fall back to parsing text otherwise.
        parsed = None
        if output_type is not None and not tool_calls:
            sdk_parsed = getattr(response, "parsed", None)
            if sdk_parsed is not None and is_pydantic_model(output_type):
                # google-genai already validated against the schema.
                parsed = sdk_parsed
            else:
                parsed = parse_text_to_output_type(text, output_type)

        return self._normalized_response(
            text=text,
            model=model,
            provider=self.PROVIDER_NAME,
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            tool_calls=tool_calls,
            raw=response,
            parsed=parsed,
        )