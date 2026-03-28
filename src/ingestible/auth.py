"""Supabase-backed API key validation with caching."""

import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

_supabase_url: str | None = None
_supabase_key: str | None = None

# Cache: token -> (is_valid, key_id_or_None, expiry_timestamp)
_cache: dict[str, tuple[bool, str | None, float]] = {}

CACHE_TTL = 60  # seconds


def init_supabase_auth() -> bool:
    """Read Supabase env vars. Returns True if Supabase auth is available."""
    global _supabase_url, _supabase_key
    _supabase_url = os.environ.get("SUPABASE_URL")
    _supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    return bool(_supabase_url and _supabase_key)


def is_supabase_auth_enabled() -> bool:
    return bool(_supabase_url and _supabase_key)


async def validate_supabase_key(
    token: str, client: httpx.AsyncClient
) -> tuple[bool, str | None]:
    """Validate a token against the Supabase api_keys table.

    Returns (is_valid, key_id). Uses a 60s TTL cache.
    """
    now = time.monotonic()

    # Check cache
    cached = _cache.get(token)
    if cached is not None:
        is_valid, key_id, expires_at = cached
        if now < expires_at:
            return is_valid, key_id

    # Cache miss — query Supabase
    try:
        resp = await client.get(
            f"{_supabase_url}/rest/v1/api_keys",
            params={
                "key": f"eq.{token}",
                "revoked": "eq.false",
                "select": "id",
            },
            headers={
                "apikey": _supabase_key,
                "Authorization": f"Bearer {_supabase_key}",
            },
        )

        if resp.status_code == 200:
            rows = resp.json()
            if rows and len(rows) == 1:
                key_id = rows[0]["id"]
                _cache[token] = (True, key_id, now + CACHE_TTL)
                return True, key_id

        # Not found or unexpected response
        _cache[token] = (False, None, now + CACHE_TTL)
        return False, None

    except httpx.HTTPError as exc:
        logger.warning("Supabase key validation failed: %s", exc)
        # Don't cache network errors — retry on next request
        return False, None


async def update_usage_stats(key_id: str, client: httpx.AsyncClient) -> None:
    """Fire-and-forget: increment request count and update last_used_at."""
    try:
        await client.post(
            f"{_supabase_url}/rest/v1/rpc/increment_api_key_usage",
            json={"p_key_id": key_id},
            headers={
                "apikey": _supabase_key,
                "Authorization": f"Bearer {_supabase_key}",
                "Content-Type": "application/json",
            },
        )
    except Exception as exc:
        logger.warning("Failed to update usage stats for key %s: %s", key_id, exc)


def invalidate_cache(token: str) -> None:
    """Remove a token from the validation cache."""
    _cache.pop(token, None)
