"""Cost tracking for ingestion pipeline."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    provider: str = ""


@dataclass
class CostBreakdown:
    """Accumulated cost data for a single ingestion run."""

    input_file_bytes: int = 0
    output_storage_bytes: int = 0
    duration_seconds: float = 0.0
    enrichment_llm: LLMUsage = field(default_factory=LLMUsage)
    embedding_api: LLMUsage = field(default_factory=LLMUsage)
    total_chunks: int = 0
    estimated_cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return {
            "input_file_bytes": self.input_file_bytes,
            "output_storage_bytes": self.output_storage_bytes,
            "duration_seconds": round(self.duration_seconds, 2),
            "enrichment": {
                "input_tokens": self.enrichment_llm.input_tokens,
                "output_tokens": self.enrichment_llm.output_tokens,
                "calls": self.enrichment_llm.calls,
                "provider": self.enrichment_llm.provider,
            },
            "embedding": {
                "tokens": self.embedding_api.input_tokens,
                "calls": self.embedding_api.calls,
                "provider": self.embedding_api.provider,
            },
            "total_chunks": self.total_chunks,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
        }

    def estimate_cost(self):
        """Estimate USD cost based on provider pricing."""
        cost = 0.0
        llm = self.enrichment_llm
        if llm.provider == "gemini":
            # Gemini 2.0 Flash: $0.10/1M input, $0.40/1M output
            cost += (llm.input_tokens / 1_000_000) * 0.10
            cost += (llm.output_tokens / 1_000_000) * 0.40
        elif llm.provider == "openai":
            # GPT-4o-mini: $0.15/1M input, $0.60/1M output
            cost += (llm.input_tokens / 1_000_000) * 0.15
            cost += (llm.output_tokens / 1_000_000) * 0.60
        elif llm.provider == "anthropic":
            # Claude Haiku: $0.25/1M input, $1.25/1M output
            cost += (llm.input_tokens / 1_000_000) * 0.25
            cost += (llm.output_tokens / 1_000_000) * 1.25

        emb = self.embedding_api
        if emb.provider == "openai":
            # text-embedding-3-small: $0.02/1M tokens
            cost += (emb.input_tokens / 1_000_000) * 0.02

        self.estimated_cost_usd = cost


# Thread-local accumulator for collecting usage during pipeline
_cost_context = threading.local()


def get_cost_tracker() -> CostBreakdown:
    if not hasattr(_cost_context, "tracker"):
        _cost_context.tracker = CostBreakdown()
    return _cost_context.tracker


def reset_cost_tracker() -> None:
    _cost_context.tracker = CostBreakdown()


def record_llm_usage(input_tokens: int, output_tokens: int, provider: str) -> None:
    t = get_cost_tracker()
    t.enrichment_llm.input_tokens += input_tokens
    t.enrichment_llm.output_tokens += output_tokens
    t.enrichment_llm.calls += 1
    t.enrichment_llm.provider = provider


class TokenBudgetExceeded(Exception):
    """Raised when a document's LLM token or cost budget is exceeded."""


def check_budget(max_tokens: int, max_cost_usd: float) -> None:
    """Check whether the current document has exceeded its LLM budget.

    Raises TokenBudgetExceeded if either the token count or estimated cost
    exceeds the configured limits.
    """
    t = get_cost_tracker()
    total_tokens = t.enrichment_llm.input_tokens + t.enrichment_llm.output_tokens
    if total_tokens > max_tokens:
        raise TokenBudgetExceeded(
            f"Token budget exceeded: {total_tokens:,} tokens used, "
            f"limit is {max_tokens:,}"
        )
    t.estimate_cost()
    if t.estimated_cost_usd > max_cost_usd:
        raise TokenBudgetExceeded(
            f"Cost budget exceeded: ${t.estimated_cost_usd:.4f} spent, "
            f"limit is ${max_cost_usd:.2f}"
        )


def record_embedding_usage(tokens: int, provider: str) -> None:
    t = get_cost_tracker()
    t.embedding_api.input_tokens += tokens
    t.embedding_api.calls += 1
    t.embedding_api.provider = provider
