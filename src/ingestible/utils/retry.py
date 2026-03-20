"""Retry decorator for LLM API calls with exponential backoff."""

from __future__ import annotations

import asyncio
import logging
from typing import TypeVar, Callable, Any

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Exceptions worth retrying (transient failures)
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


def _is_retryable(exc: Exception) -> bool:
    """Check if an exception is transient and worth retrying."""
    # OpenAI / Anthropic exceptions with status_code attribute
    if hasattr(exc, "status_code"):
        return getattr(exc, "status_code", 0) in _RETRYABLE_STATUS_CODES

    # Connection errors (both libraries)
    exc_type = type(exc).__name__
    if any(name in exc_type for name in ("APIConnectionError", "ConnectError", "Timeout", "ConnectionError")):
        return True

    return False


async def retry_llm_call(
    coro_func: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs: Any,
) -> Any:
    """Call an async function with exponential backoff retry on transient failures.

    Args:
        coro_func: The async function to call.
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay in seconds (doubles each retry).
        *args, **kwargs: Passed to coro_func.

    Returns:
        The result of coro_func.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt >= max_retries or not _is_retryable(e):
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "LLM call failed (attempt %d/%d): %s — retrying in %.1fs",
                attempt + 1, max_retries + 1, e, delay,
            )
            await asyncio.sleep(delay)
    raise last_exc  # unreachable, but satisfies type checker
