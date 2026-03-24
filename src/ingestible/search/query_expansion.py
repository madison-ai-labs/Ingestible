"""Query expansion techniques for improving retrieval quality.

HyDE (Hypothetical Document Embeddings): generates a hypothetical answer passage
via LLM and uses that for vector search, bridging the query-document vocabulary gap.

Sub-question decomposition: breaks complex queries into simpler sub-queries,
searches each independently, and lets the caller merge results.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from ingestible.config import Settings
from ingestible.utils.retry import retry_llm_call

logger = logging.getLogger(__name__)

_HYDE_SYSTEM = (
    "You are a helpful assistant. Write a short passage (2-3 sentences) that would "
    "directly answer this question. Write only the passage, no preamble."
)

_DECOMPOSE_SYSTEM = (
    "You are a helpful assistant. Break the following complex question into simpler "
    "sub-questions that, when answered together, would answer the original question. "
    "Return one sub-question per line. Do not number them. Do not include any other text. "
    "If the question is already simple enough, return it unchanged as a single line."
)


@dataclass
class QueryExpansionConfig:
    """Configuration for query expansion techniques."""

    hyde_enabled: bool = False
    sub_questions_enabled: bool = False
    max_sub_questions: int = 3


class HyDEExpander:
    """Generate a hypothetical document passage that would answer the query.

    The hypothetical passage is embedded instead of (or alongside) the raw query,
    which tends to land closer to real relevant documents in embedding space.
    """

    def __init__(self, settings: Settings):
        self._settings = settings

    async def expand(self, query: str) -> str:
        """Generate a hypothetical document passage that would answer the query."""
        if self._settings.llm_provider == "anthropic":
            return await self._expand_anthropic(query)
        return await self._expand_openai(query)

    def expand_sync(self, query: str) -> str:
        """Synchronous wrapper for expand()."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.expand(query))
        finally:
            loop.close()

    async def _expand_openai(self, query: str) -> str:
        import openai

        client = openai.AsyncOpenAI(
            api_key=self._settings.openai_api_key,
            timeout=self._settings.llm_timeout,
        )

        async def _call() -> str:
            response = await client.chat.completions.create(
                model=self._settings.openai_model,
                messages=[
                    {"role": "system", "content": _HYDE_SYSTEM},
                    {"role": "user", "content": query},
                ],
                temperature=0.7,
                max_tokens=256,
            )
            return response.choices[0].message.content or ""

        result = await retry_llm_call(
            _call,
            max_retries=self._settings.llm_max_retries,
            base_delay=self._settings.llm_retry_base_delay,
        )
        return result.strip()

    async def _expand_anthropic(self, query: str) -> str:
        import anthropic

        client = anthropic.AsyncAnthropic(
            api_key=self._settings.anthropic_api_key,
            timeout=self._settings.llm_timeout,
        )

        async def _call() -> str:
            response = await client.messages.create(
                model=self._settings.anthropic_model,
                max_tokens=256,
                system=_HYDE_SYSTEM,
                messages=[{"role": "user", "content": query}],
                temperature=0.7,
            )
            text_block = next((b for b in response.content if b.type == "text"), None)
            return text_block.text if text_block else ""

        result = await retry_llm_call(
            _call,
            max_retries=self._settings.llm_max_retries,
            base_delay=self._settings.llm_retry_base_delay,
        )
        return result.strip()


class SubQuestionDecomposer:
    """Break a complex query into simpler sub-questions for independent retrieval."""

    def __init__(self, settings: Settings):
        self._settings = settings

    async def decompose(self, query: str, max_sub_questions: int = 3) -> list[str]:
        """Break a complex query into simpler sub-questions.

        Returns a list of sub-questions. If the query is simple or the LLM
        determines no decomposition is needed, returns [query].
        """
        if self._settings.llm_provider == "anthropic":
            return await self._decompose_anthropic(query, max_sub_questions)
        return await self._decompose_openai(query, max_sub_questions)

    async def _decompose_openai(self, query: str, max_sub_questions: int) -> list[str]:
        import openai

        client = openai.AsyncOpenAI(
            api_key=self._settings.openai_api_key,
            timeout=self._settings.llm_timeout,
        )

        async def _call() -> str:
            response = await client.chat.completions.create(
                model=self._settings.openai_model,
                messages=[
                    {"role": "system", "content": _DECOMPOSE_SYSTEM},
                    {"role": "user", "content": query},
                ],
                temperature=0.3,
                max_tokens=512,
            )
            return response.choices[0].message.content or ""

        raw = await retry_llm_call(
            _call,
            max_retries=self._settings.llm_max_retries,
            base_delay=self._settings.llm_retry_base_delay,
        )
        return self._parse_sub_questions(raw, query, max_sub_questions)

    async def _decompose_anthropic(self, query: str, max_sub_questions: int) -> list[str]:
        import anthropic

        client = anthropic.AsyncAnthropic(
            api_key=self._settings.anthropic_api_key,
            timeout=self._settings.llm_timeout,
        )

        async def _call() -> str:
            response = await client.messages.create(
                model=self._settings.anthropic_model,
                max_tokens=512,
                system=_DECOMPOSE_SYSTEM,
                messages=[{"role": "user", "content": query}],
                temperature=0.3,
            )
            text_block = next((b for b in response.content if b.type == "text"), None)
            return text_block.text if text_block else ""

        raw = await retry_llm_call(
            _call,
            max_retries=self._settings.llm_max_retries,
            base_delay=self._settings.llm_retry_base_delay,
        )
        return self._parse_sub_questions(raw, query, max_sub_questions)

    @staticmethod
    def _parse_sub_questions(raw: str, original_query: str, max_count: int) -> list[str]:
        """Parse LLM output into a list of sub-questions."""
        lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]
        if not lines:
            return [original_query]
        # Truncate to max_count
        return lines[:max_count]


async def expand_query(
    query: str,
    config: QueryExpansionConfig,
    settings: Settings,
) -> list[str]:
    """Apply configured query expansion techniques.

    Returns a list of queries to search with. If no expansion is enabled,
    returns [query]. Results from multiple queries should be merged by the caller.
    """
    if not config.hyde_enabled and not config.sub_questions_enabled:
        return [query]

    queries: list[str] = []

    if config.hyde_enabled:
        try:
            expander = HyDEExpander(settings)
            hypothetical = await expander.expand(query)
            if hypothetical:
                queries.append(hypothetical)
            else:
                logger.warning("HyDE expansion returned empty result, falling back to raw query")
                queries.append(query)
        except Exception:
            logger.exception("HyDE expansion failed, falling back to raw query")
            queries.append(query)

    if config.sub_questions_enabled:
        try:
            decomposer = SubQuestionDecomposer(settings)
            sub_questions = await decomposer.decompose(
                query, max_sub_questions=config.max_sub_questions
            )
            queries.extend(sub_questions)
        except Exception:
            logger.exception("Sub-question decomposition failed, falling back to raw query")
            if not queries:
                queries.append(query)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique.append(q)

    return unique if unique else [query]
