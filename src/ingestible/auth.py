"""Supabase-backed API key validation with caching."""

import logging
import os
import time
from dataclasses import dataclass
from datetime import date

import httpx

logger = logging.getLogger(__name__)

_supabase_url: str | None = None
_supabase_key: str | None = None

# Cache: token -> (is_valid, key_id_or_None, expiry_timestamp)
_cache: dict[str, tuple[bool, str | None, float]] = {}

CACHE_TTL = 60  # seconds


@dataclass
class UserQuotas:
    """Resolved quota and usage snapshot for an API key's owner."""

    tier: str
    max_documents: int
    max_file_size_mb: int
    enrichment_enabled: bool
    requests_per_day: int
    requests_today: int
    documents_ingested: int
    suspended: bool


class QuotaExceededError(Exception):
    """Raised when a user has exceeded their tier's quota."""


# Cache: key_id -> (UserQuotas, expiry_timestamp)
_quota_cache: dict[str, tuple[UserQuotas, float]] = {}

QUOTA_CACHE_TTL = 30  # seconds


def init_supabase_auth() -> bool:
    """Read Supabase env vars. Returns True if Supabase auth is available."""
    global _supabase_url, _supabase_key
    _supabase_url = os.environ.get("SUPABASE_URL")
    _supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    return bool(_supabase_url and _supabase_key)


def is_supabase_auth_enabled() -> bool:
    return bool(_supabase_url and _supabase_key)


async def validate_supabase_key(token: str, client: httpx.AsyncClient) -> tuple[bool, str | None]:
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


async def update_ingestion_stats(
    key_id: str,
    client: httpx.AsyncClient,
    tokens_used: int = 0,
    bytes_uploaded: int = 0,
    documents_ingested: int = 0,
) -> None:
    """Fire-and-forget: increment ingestion-related counters on the api_keys table."""
    try:
        await client.post(
            f"{_supabase_url}/rest/v1/rpc/update_api_key_ingestion_stats",
            json={
                "p_key_id": key_id,
                "p_tokens_used": tokens_used,
                "p_bytes_uploaded": bytes_uploaded,
                "p_documents_ingested": documents_ingested,
            },
            headers={
                "apikey": _supabase_key,
                "Authorization": f"Bearer {_supabase_key}",
                "Content-Type": "application/json",
            },
        )
    except Exception as exc:
        logger.warning("Failed to update ingestion stats: %s", exc)


async def get_user_quotas(key_id: str, client: httpx.AsyncClient) -> UserQuotas | None:
    """Fetch quota limits and current usage for the owner of *key_id*.

    Returns ``None`` if the lookup fails (network error, missing rows, etc.)
    so callers can treat quota checks as a soft gate.

    Results are cached for 30 seconds.
    """
    now = time.monotonic()

    # Check cache
    cached = _quota_cache.get(key_id)
    if cached is not None:
        quotas, expires_at = cached
        if now < expires_at:
            return quotas

    headers = {
        "apikey": _supabase_key,
        "Authorization": f"Bearer {_supabase_key}",
    }

    try:
        # 1. Fetch api_key row — user_id + counters
        resp = await client.get(
            f"{_supabase_url}/rest/v1/api_keys",
            params={
                "id": f"eq.{key_id}",
                "select": "user_id,requests_count,documents_ingested,bytes_uploaded",
            },
            headers=headers,
        )
        if resp.status_code != 200 or not resp.json():
            return None
        key_row = resp.json()[0]
        user_id = key_row["user_id"]

        # 2. Fetch user profile — role (= tier) + suspended flag
        resp = await client.get(
            f"{_supabase_url}/rest/v1/profiles",
            params={
                "id": f"eq.{user_id}",
                "select": "role,suspended",
            },
            headers=headers,
        )
        if resp.status_code != 200 or not resp.json():
            return None
        user_row = resp.json()[0]
        tier = user_row.get("role", "free")
        suspended = bool(user_row.get("suspended", False))

        # 3. Fetch tier limits
        resp = await client.get(
            f"{_supabase_url}/rest/v1/tier_limits",
            params={
                "tier": f"eq.{tier}",
                "select": "requests_per_day,max_documents,max_file_size_mb,enrichment_enabled",
            },
            headers=headers,
        )
        if resp.status_code != 200 or not resp.json():
            return None
        limits = resp.json()[0]

        # 4. Fetch today's request count from api_key_usage
        today_str = date.today().isoformat()
        resp = await client.get(
            f"{_supabase_url}/rest/v1/api_key_usage",
            params={
                "api_key_id": f"eq.{key_id}",
                "date": f"eq.{today_str}",
                "select": "requests",
            },
            headers=headers,
        )
        requests_today = 0
        if resp.status_code == 200 and resp.json():
            for row in resp.json():
                requests_today += row.get("requests", 0)

        quotas = UserQuotas(
            tier=tier,
            max_documents=limits["max_documents"],
            max_file_size_mb=limits["max_file_size_mb"],
            enrichment_enabled=limits["enrichment_enabled"],
            requests_per_day=limits["requests_per_day"],
            requests_today=requests_today,
            documents_ingested=key_row.get("documents_ingested", 0),
            suspended=suspended,
        )
        _quota_cache[key_id] = (quotas, now + QUOTA_CACHE_TTL)
        return quotas

    except Exception as exc:
        logger.warning("Failed to fetch user quotas for key %s: %s", key_id, exc)
        return None


def invalidate_cache(token: str) -> None:
    """Remove a token from the validation cache."""
    _cache.pop(token, None)
