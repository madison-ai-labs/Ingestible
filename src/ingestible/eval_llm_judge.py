"""LLM-as-judge evaluation for retrieval quality.

Complements the metrics-based eval module (eval.py) by using an LLM to
assess whether retrieved chunks actually *answer* the query well.

Scores three dimensions on a 0–1 scale:
  - Faithfulness: Does the content accurately answer the query?
  - Relevance: How relevant are the retrieved chunks?
  - Completeness: Do the chunks together cover all aspects of the query?
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from ingestible.config import Settings
from ingestible.eval import EvalQuery, _generate_synthetic_queries
from ingestible.pipeline.stage5_embedding import Embedder
from ingestible.pipeline.stage6_storage import load_chunks
from ingestible.search.hybrid import load_searcher
from ingestible.utils.retry import retry_llm_call

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class JudgeConfig:
    """Configuration for the LLM judge."""

    enabled: bool = False
    concurrency: int = 5


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


@dataclass
class JudgeScore:
    """LLM judge score for a single query-results pair."""

    query: str
    faithfulness: float  # 0.0-1.0
    relevance: float  # 0.0-1.0
    completeness: float  # 0.0-1.0
    reasoning: str  # LLM's explanation
    chunk_ids: list[str] = field(default_factory=list)


@dataclass
class JudgeReport:
    """Aggregate LLM judge scores across all queries."""

    doc_id: str
    total_queries: int
    mean_faithfulness: float
    mean_relevance: float
    mean_completeness: float
    scores: list[JudgeScore] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "total_queries": self.total_queries,
            "mean_faithfulness": round(self.mean_faithfulness, 4),
            "mean_relevance": round(self.mean_relevance, 4),
            "mean_completeness": round(self.mean_completeness, 4),
            "scores": [
                {
                    "query": s.query,
                    "faithfulness": round(s.faithfulness, 4),
                    "relevance": round(s.relevance, 4),
                    "completeness": round(s.completeness, 4),
                    "reasoning": s.reasoning,
                    "chunk_ids": s.chunk_ids,
                }
                for s in self.scores
            ],
        }

    def summary(self) -> str:
        lines = [
            f"LLM Judge: {self.doc_id} — {self.total_queries} queries",
            f"  Faithfulness:  {self.mean_faithfulness:.4f}",
            f"  Relevance:     {self.mean_relevance:.4f}",
            f"  Completeness:  {self.mean_completeness:.4f}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_JUDGE_PROMPT = """\
You are an expert retrieval-quality judge. Given a user query and a set of \
retrieved text chunks, evaluate how well the chunks answer the query.

Rate each dimension on a 0.0–1.0 scale:
- **faithfulness**: Does the retrieved content contain information that \
accurately answers the query? (1.0 = fully accurate, 0.0 = contradicts or \
is entirely unrelated)
- **relevance**: How relevant are the retrieved chunks to the query? \
(1.0 = all chunks highly relevant, 0.0 = none relevant)
- **completeness**: Do the chunks together cover all aspects of the query? \
(1.0 = fully covers the query, 0.0 = misses all key aspects)

Respond with ONLY a JSON object (no markdown fences, no extra text):
{{"faithfulness": <float>, "relevance": <float>, "completeness": <float>, \
"reasoning": "<brief explanation>"}}

Query: {query}

Retrieved chunks:
{chunks}
"""


def _build_prompt(query: str, contents: list[str]) -> str:
    """Format the judge prompt with the query and retrieved chunk contents."""
    numbered = "\n\n".join(f"--- Chunk {i + 1} ---\n{text}" for i, text in enumerate(contents))
    return _JUDGE_PROMPT.format(query=query, chunks=numbered)


def _parse_judge_response(raw: str) -> dict:
    """Parse the LLM response JSON, stripping markdown fences if present."""
    text = raw.strip()
    # Strip ```json ... ``` wrapper if the model included one
    if text.startswith("```"):
        # Remove first line and last line
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)


def _clamp(value: float) -> float:
    """Clamp a float to [0.0, 1.0]."""
    return max(0.0, min(1.0, float(value)))


# ---------------------------------------------------------------------------
# LLM Judge
# ---------------------------------------------------------------------------


class LLMJudge:
    """Uses an LLM to evaluate retrieval quality."""

    def __init__(self, settings: Settings):
        self._settings = settings

    async def _call_openai(self, prompt: str) -> str:
        import openai

        client = openai.AsyncOpenAI(
            api_key=self._settings.openai_api_key,
            timeout=self._settings.llm_timeout,
        )
        response = await client.chat.completions.create(
            model=self._settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        return response.choices[0].message.content

    async def _call_anthropic(self, prompt: str) -> str:
        import anthropic

        client = anthropic.AsyncAnthropic(
            api_key=self._settings.anthropic_api_key,
            timeout=self._settings.llm_timeout,
        )
        response = await client.messages.create(
            model=self._settings.anthropic_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    async def _call_llm(self, prompt: str) -> str:
        """Dispatch to the configured LLM provider."""
        if self._settings.llm_provider == "anthropic":
            return await self._call_anthropic(prompt)
        return await self._call_openai(prompt)

    async def score(
        self,
        query: str,
        retrieved_contents: list[str],
        chunk_ids: list[str] | None = None,
    ) -> JudgeScore:
        """Score a single query-results pair using the LLM.

        Sends a structured prompt asking the LLM to rate faithfulness,
        relevance, and completeness on a 0–1 scale with reasoning.
        """
        if not retrieved_contents:
            return JudgeScore(
                query=query,
                faithfulness=0.0,
                relevance=0.0,
                completeness=0.0,
                reasoning="No chunks retrieved.",
                chunk_ids=chunk_ids or [],
            )

        prompt = _build_prompt(query, retrieved_contents)

        raw = await retry_llm_call(
            self._call_llm,
            prompt,
            max_retries=self._settings.llm_max_retries,
            base_delay=self._settings.llm_retry_base_delay,
        )

        parsed = _parse_judge_response(raw)

        return JudgeScore(
            query=query,
            faithfulness=_clamp(parsed.get("faithfulness", 0.0)),
            relevance=_clamp(parsed.get("relevance", 0.0)),
            completeness=_clamp(parsed.get("completeness", 0.0)),
            reasoning=parsed.get("reasoning", ""),
            chunk_ids=chunk_ids or [],
        )

    async def evaluate(
        self,
        queries_and_results: list[tuple[str, list[str]]],
        doc_id: str = "",
        concurrency: int = 5,
    ) -> JudgeReport:
        """Evaluate multiple query-result pairs with controlled concurrency.

        Args:
            queries_and_results: List of (query, [chunk_contents]) tuples.
            doc_id: Document identifier for the report.
            concurrency: Max parallel LLM calls.

        Returns:
            JudgeReport with aggregate and per-query scores.
        """
        sem = asyncio.Semaphore(concurrency)

        async def _score_one(query: str, contents: list[str]) -> JudgeScore:
            async with sem:
                return await self.score(query, contents)

        tasks = [
            asyncio.ensure_future(_score_one(q, contents)) for q, contents in queries_and_results
        ]
        scores: list[JudgeScore] = await asyncio.gather(*tasks)

        n = len(scores)
        mean_faith = sum(s.faithfulness for s in scores) / n if n else 0.0
        mean_rel = sum(s.relevance for s in scores) / n if n else 0.0
        mean_comp = sum(s.completeness for s in scores) / n if n else 0.0

        return JudgeReport(
            doc_id=doc_id,
            total_queries=n,
            mean_faithfulness=mean_faith,
            mean_relevance=mean_rel,
            mean_completeness=mean_comp,
            scores=scores,
        )


# ---------------------------------------------------------------------------
# Integration helper
# ---------------------------------------------------------------------------


async def evaluate_with_judge(
    doc_id: str,
    settings: Settings,
    queries: list[EvalQuery] | None = None,
    k: int = 5,
    concurrency: int = 5,
) -> JudgeReport:
    """Run LLM-as-judge evaluation on a document.

    Searches for each query, then asks the LLM to judge the results.

    Args:
        doc_id: Document to evaluate.
        settings: Ingestible settings (must include LLM provider config).
        queries: Evaluation queries. If *None*, synthetic queries are
            generated from enriched chunk hypothetical questions.
        k: Number of results to retrieve per query.
        concurrency: Maximum parallel LLM judge calls.

    Returns:
        JudgeReport with per-query and aggregate scores.
    """
    doc_dir = settings.documents_dir / doc_id
    if not doc_dir.exists():
        raise FileNotFoundError(f"Document not found: {doc_id}")

    chunks = load_chunks(doc_dir)
    embedder = Embedder(settings)
    searcher = load_searcher(doc_dir, chunks, embedder, settings)

    if queries is None:
        queries = _generate_synthetic_queries(chunks)
        if not queries:
            raise ValueError(
                f"No hypothetical questions found in {doc_id}. "
                "Run enrichment first, or provide manual Q&A pairs."
            )

    logger.info(
        "Running LLM judge on %d queries against %s @ K=%d",
        len(queries),
        doc_id,
        k,
    )

    # Search and collect (query, chunk_contents) pairs
    queries_and_results: list[tuple[str, list[str]]] = []
    for eq in queries:
        response = searcher.search(eq.query, n_results=k)
        contents = [r.content for r in response.results]
        queries_and_results.append((eq.query, contents))

    judge = LLMJudge(settings)
    return await judge.evaluate(queries_and_results, doc_id=doc_id, concurrency=concurrency)
