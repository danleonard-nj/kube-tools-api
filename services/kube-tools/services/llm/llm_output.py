"""
Structured output helpers shared across LLM providers.

Supports two `output_type` shapes:
- A Pydantic v2 BaseModel subclass -> schema-enforced output, parsed instance
- The literal `dict` (or string "json") -> loose JSON mode, parsed dict

Each provider uses these helpers to:
1. Convert the requested type into the schema format their SDK accepts.
2. Parse the model's text output back into the requested type.
3. Raise StructuredOutputError on parse failure with a useful message.
"""

import hashlib
import json
from typing import Any, Union

from pydantic import BaseModel, ValidationError

# A type the caller passes to request structured output.
# Either a BaseModel subclass, or `dict` / "json" for loose JSON mode.
OutputType = Union[type[BaseModel], type[dict], str]


class StructuredOutputError(Exception):
    """
    Raised when the model's response can't be parsed into the requested
    output_type. Attributes:
        raw_text: The text returned by the model.
        output_type: The type that was requested.
        underlying: The exception that triggered the failure (json.JSONDecodeError,
                    pydantic.ValidationError, etc.).
    """

    def __init__(
        self,
        message: str,
        raw_text: str,
        output_type: Any,
        underlying: Exception | None = None,
    ):
        super().__init__(message)
        self.raw_text = raw_text
        self.output_type = output_type
        self.underlying = underlying


def is_pydantic_model(output_type: Any) -> bool:
    return isinstance(output_type, type) and issubclass(output_type, BaseModel)


def is_loose_json(output_type: Any) -> bool:
    """True for `dict` or the string 'json'."""
    if output_type is dict:
        return True
    if isinstance(output_type, str) and output_type.lower() == "json":
        return True
    return False


def normalize_output_type(output_type: Any) -> Any:
    """
    Validate the output_type argument. Returns the type unchanged if valid,
    raises ValueError otherwise.
    """
    if output_type is None:
        return None
    if is_pydantic_model(output_type):
        return output_type
    if is_loose_json(output_type):
        return output_type
    raise ValueError(
        f"output_type must be a Pydantic BaseModel subclass, dict, or 'json'; "
        f"got {output_type!r}"
    )


def schema_fingerprint(output_type: Any) -> str:
    """
    Stable identifier for an output_type, used in cache keys so cached
    responses for `output_type=ModelA` don't collide with `output_type=ModelB`.
    """
    if output_type is None:
        return "none"
    if is_loose_json(output_type):
        return "json"
    if is_pydantic_model(output_type):
        schema_json = json.dumps(
            output_type.model_json_schema(), sort_keys=True
        )
        return (
            f"{output_type.__module__}.{output_type.__name__}:"
            f"{hashlib.sha256(schema_json.encode()).hexdigest()[:16]}"
        )
    return str(output_type)


# ---------------------------------------------------------------------------
# OpenAI strict-schema conversion
# ---------------------------------------------------------------------------
#
# OpenAI Responses API Structured Outputs require a JSON schema with these
# constraints applied to every object node:
#   - additionalProperties: false
#   - every property listed in `required`
#   - optional fields expressed as a union with null
#
# Pydantic's model_json_schema() doesn't produce this shape by default,
# so we transform it.


def pydantic_to_openai_strict_schema(model_cls: type[BaseModel]) -> dict:
    """
    Produce a JSON schema for `model_cls` that satisfies OpenAI's strict
    Structured Outputs requirements.
    """
    schema = model_cls.model_json_schema()
    # Inline $refs so OpenAI sees a self-contained schema. Pydantic places
    # nested models under $defs; we resolve them here.
    schema = _inline_refs(schema)
    schema = _apply_strict_constraints(schema)
    return schema


def _inline_refs(schema: dict) -> dict:
    defs = schema.pop("$defs", {}) or schema.pop("definitions", {})
    if not defs:
        return schema

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node and len(node) == 1:
                ref = node["$ref"]
                # Refs look like "#/$defs/ModelName"
                name = ref.split("/")[-1]
                if name in defs:
                    return resolve(defs[name])
                return node
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def _apply_strict_constraints(node: Any) -> Any:
    if isinstance(node, dict):
        # If this node describes an object, lock it down.
        if node.get("type") == "object" or "properties" in node:
            properties = node.get("properties", {})
            node["additionalProperties"] = False
            # OpenAI strict mode requires every property be listed as required.
            # Pydantic's "optional" (Union with None) becomes a type union; we
            # leave that alone and just mark all keys required.
            node["required"] = list(properties.keys())
            for prop_schema in properties.values():
                _apply_strict_constraints(prop_schema)
        # Recurse into composite schemas.
        for key in ("items", "anyOf", "allOf", "oneOf"):
            if key in node:
                _apply_strict_constraints(node[key])
    elif isinstance(node, list):
        for item in node:
            _apply_strict_constraints(item)
    return node


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_text_to_output_type(text: str, output_type: Any) -> Any:
    """
    Parse a JSON string into the requested output_type.

    - For Pydantic models: validates against the model.
    - For dict / 'json': returns the parsed JSON value.

    Raises StructuredOutputError on any parse or validation failure.
    """
    if output_type is None:
        return None

    if not text or not text.strip():
        raise StructuredOutputError(
            "Model returned empty text; cannot parse structured output.",
            raw_text=text,
            output_type=output_type,
        )

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise StructuredOutputError(
            f"Model output was not valid JSON: {e.msg} at line {e.lineno} col {e.colno}",
            raw_text=text,
            output_type=output_type,
            underlying=e,
        ) from e

    if is_loose_json(output_type):
        return data

    if is_pydantic_model(output_type):
        try:
            return output_type.model_validate(data)
        except ValidationError as e:
            raise StructuredOutputError(
                f"Model output did not match {output_type.__name__} schema: {e}",
                raw_text=text,
                output_type=output_type,
                underlying=e,
            ) from e

    raise StructuredOutputError(
        f"Unknown output_type: {output_type!r}",
        raw_text=text,
        output_type=output_type,
    )


def parse_value_to_output_type(value: Any, output_type: Any) -> Any:
    """
    Parse an already-deserialized value (dict from a tool_use block, etc.)
    into the requested output_type. Used for Anthropic where the structured
    output arrives as a dict, not a JSON string.
    """
    if output_type is None:
        return value
    if is_loose_json(output_type):
        return value
    if is_pydantic_model(output_type):
        try:
            return output_type.model_validate(value)
        except ValidationError as e:
            raise StructuredOutputError(
                f"Model output did not match {output_type.__name__} schema: {e}",
                raw_text=json.dumps(value, default=str),
                output_type=output_type,
                underlying=e,
            ) from e
    raise StructuredOutputError(
        f"Unknown output_type: {output_type!r}",
        raw_text=json.dumps(value, default=str),
        output_type=output_type,
    )