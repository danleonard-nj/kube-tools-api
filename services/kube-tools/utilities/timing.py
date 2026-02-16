"""Lightweight timing helpers for stage-level bottleneck logging."""

from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Any, Dict, Iterator, Optional


def _fmt_fields(fields: Dict[str, Any]) -> str:
    if not fields:
        return ""

    parts = []
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")

    return " " + " ".join(parts) if parts else ""


@contextmanager
def log_stage_timing(
    logger,
    stage: str,
    *,
    level: str = "info",
    fields: Optional[Dict[str, Any]] = None,
) -> Iterator[None]:
    """Log the duration of a named stage.

    Emits a single log line on exit:
        [timing] stage=<stage> duration_ms=<int> <optional fields>

    Args:
        logger: Logger instance (must support .info/.debug/.warning/etc.)
        stage: Stage name for grouping in logs
        level: Logger method name to call (default 'info')
        fields: Extra key/value fields for correlation (filename, chunk_index, etc.)
    """
    start = perf_counter()
    try:
        yield
    finally:
        duration_ms = int((perf_counter() - start) * 1000)
        extra = _fmt_fields(fields or {})
        log_fn = getattr(logger, level, None) or getattr(logger, "info")
        log_fn(f"[timing] stage={stage} duration_ms={duration_ms}{extra}")
