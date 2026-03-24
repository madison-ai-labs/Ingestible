"""Tests for the LLM-as-judge evaluation module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ingestible.eval_llm_judge import (
    JudgeConfig,
    JudgeReport,
    JudgeScore,
    LLMJudge,
    _build_prompt,
    _clamp,
    _parse_judge_response,
    evaluate_with_judge,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides):
    """Create a minimal Settings object for testing."""
    from ingestible.config import Settings

    defaults = {
        "llm_provider": "openai",
        "openai_api_key": "test-key",
        "openai_model": "gpt-4o-mini",
        "anthropic_api_key": "test-key",
        "anthropic_model": "claude-haiku-4-5-20251001",
        "llm_timeout": 30,
        "llm_max_retries": 0,
        "llm_retry_base_delay": 0.0,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _good_json(
    faithfulness: float = 0.9,
    relevance: float = 0.8,
    completeness: float = 0.7,
    reasoning: str = "Chunks cover the query well.",
) -> str:
    return json.dumps(
        {
            "faithfulness": faithfulness,
            "relevance": relevance,
            "completeness": completeness,
            "reasoning": reasoning,
        }
    )


# ---------------------------------------------------------------------------
# JudgeScore
# ---------------------------------------------------------------------------


class TestJudgeScore:
    def test_creation_defaults(self):
        s = JudgeScore(
            query="What is X?",
            faithfulness=0.9,
            relevance=0.8,
            completeness=0.7,
            reasoning="Good.",
        )
        assert s.query == "What is X?"
        assert s.faithfulness == 0.9
        assert s.relevance == 0.8
        assert s.completeness == 0.7
        assert s.reasoning == "Good."
        assert s.chunk_ids == []

    def test_creation_with_chunk_ids(self):
        s = JudgeScore(
            query="q",
            faithfulness=1.0,
            relevance=1.0,
            completeness=1.0,
            reasoning="Perfect.",
            chunk_ids=["c1", "c2"],
        )
        assert s.chunk_ids == ["c1", "c2"]


# ---------------------------------------------------------------------------
# JudgeReport
# ---------------------------------------------------------------------------


class TestJudgeReport:
    def _make_report(self) -> JudgeReport:
        scores = [
            JudgeScore("q1", 0.9, 0.8, 0.7, "ok", ["c1"]),
            JudgeScore("q2", 0.7, 0.6, 0.5, "meh", ["c2"]),
        ]
        return JudgeReport(
            doc_id="doc-1",
            total_queries=2,
            mean_faithfulness=0.8,
            mean_relevance=0.7,
            mean_completeness=0.6,
            scores=scores,
        )

    def test_to_dict_structure(self):
        report = self._make_report()
        d = report.to_dict()
        assert d["doc_id"] == "doc-1"
        assert d["total_queries"] == 2
        assert d["mean_faithfulness"] == 0.8
        assert d["mean_relevance"] == 0.7
        assert d["mean_completeness"] == 0.6
        assert len(d["scores"]) == 2
        assert d["scores"][0]["query"] == "q1"
        assert d["scores"][0]["chunk_ids"] == ["c1"]

    def test_to_dict_rounding(self):
        report = JudgeReport(
            doc_id="d",
            total_queries=1,
            mean_faithfulness=0.33333,
            mean_relevance=0.66666,
            mean_completeness=0.99999,
            scores=[JudgeScore("q", 0.33333, 0.66666, 0.99999, "r")],
        )
        d = report.to_dict()
        assert d["mean_faithfulness"] == 0.3333
        assert d["mean_relevance"] == 0.6667
        assert d["mean_completeness"] == 1.0

    def test_summary_formatting(self):
        report = self._make_report()
        s = report.summary()
        assert "LLM Judge: doc-1" in s
        assert "2 queries" in s
        assert "Faithfulness:" in s
        assert "Relevance:" in s
        assert "Completeness:" in s
        assert "0.8000" in s
        assert "0.7000" in s
        assert "0.6000" in s


# ---------------------------------------------------------------------------
# JudgeConfig
# ---------------------------------------------------------------------------


class TestJudgeConfig:
    def test_defaults(self):
        cfg = JudgeConfig()
        assert cfg.enabled is False
        assert cfg.concurrency == 5

    def test_custom(self):
        cfg = JudgeConfig(enabled=True, concurrency=10)
        assert cfg.enabled is True
        assert cfg.concurrency == 10


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


class TestPromptHelpers:
    def test_build_prompt_includes_query(self):
        prompt = _build_prompt("How does X work?", ["chunk text here"])
        assert "How does X work?" in prompt
        assert "chunk text here" in prompt

    def test_build_prompt_numbers_chunks(self):
        prompt = _build_prompt("q", ["first", "second"])
        assert "Chunk 1" in prompt
        assert "Chunk 2" in prompt

    def test_parse_judge_response_plain_json(self):
        raw = _good_json()
        parsed = _parse_judge_response(raw)
        assert parsed["faithfulness"] == 0.9

    def test_parse_judge_response_with_markdown_fences(self):
        raw = "```json\n" + _good_json() + "\n```"
        parsed = _parse_judge_response(raw)
        assert parsed["relevance"] == 0.8

    def test_parse_judge_response_bad_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_judge_response("not json at all")

    def test_clamp(self):
        assert _clamp(0.5) == 0.5
        assert _clamp(-0.1) == 0.0
        assert _clamp(1.5) == 1.0
        assert _clamp(0) == 0.0
        assert _clamp(1) == 1.0


# ---------------------------------------------------------------------------
# LLMJudge.score — OpenAI provider
# ---------------------------------------------------------------------------


class TestLLMJudgeScoreOpenAI:
    async def test_score_returns_judge_score(self):
        settings = _make_settings(llm_provider="openai")
        judge = LLMJudge(settings)
        judge._call_llm = AsyncMock(return_value=_good_json())

        result = await judge.score("What is X?", ["chunk about X"], chunk_ids=["c1"])

        assert isinstance(result, JudgeScore)
        assert result.faithfulness == 0.9
        assert result.relevance == 0.8
        assert result.completeness == 0.7
        assert result.reasoning == "Chunks cover the query well."
        assert result.chunk_ids == ["c1"]

    async def test_score_empty_contents(self):
        settings = _make_settings(llm_provider="openai")
        judge = LLMJudge(settings)

        result = await judge.score("query", [], chunk_ids=["c1"])

        assert result.faithfulness == 0.0
        assert result.relevance == 0.0
        assert result.completeness == 0.0
        assert "No chunks" in result.reasoning

    async def test_score_clamps_out_of_range(self):
        settings = _make_settings(llm_provider="openai")
        judge = LLMJudge(settings)

        bad_json = json.dumps(
            {"faithfulness": 1.5, "relevance": -0.2, "completeness": 0.5, "reasoning": "oops"}
        )
        judge._call_llm = AsyncMock(return_value=bad_json)

        result = await judge.score("q", ["text"])

        assert result.faithfulness == 1.0
        assert result.relevance == 0.0
        assert result.completeness == 0.5


# ---------------------------------------------------------------------------
# LLMJudge.score — Anthropic provider
# ---------------------------------------------------------------------------


class TestLLMJudgeScoreAnthropic:
    async def test_score_anthropic(self):
        settings = _make_settings(llm_provider="anthropic")
        judge = LLMJudge(settings)
        judge._call_llm = AsyncMock(return_value=_good_json(0.85, 0.75, 0.65, "Solid."))

        result = await judge.score("q", ["text"])

        assert result.faithfulness == 0.85
        assert result.relevance == 0.75
        assert result.completeness == 0.65
        assert result.reasoning == "Solid."


# ---------------------------------------------------------------------------
# LLMJudge — provider dispatch (verify _call_openai / _call_anthropic)
# ---------------------------------------------------------------------------


class TestLLMJudgeProviderDispatch:
    async def test_openai_dispatch(self):
        settings = _make_settings(llm_provider="openai")
        judge = LLMJudge(settings)
        judge._call_openai = AsyncMock(return_value=_good_json())
        judge._call_anthropic = AsyncMock()

        await judge.score("q", ["text"])

        judge._call_openai.assert_called_once()
        judge._call_anthropic.assert_not_called()

    async def test_anthropic_dispatch(self):
        settings = _make_settings(llm_provider="anthropic")
        judge = LLMJudge(settings)
        judge._call_openai = AsyncMock()
        judge._call_anthropic = AsyncMock(return_value=_good_json())

        await judge.score("q", ["text"])

        judge._call_anthropic.assert_called_once()
        judge._call_openai.assert_not_called()


# ---------------------------------------------------------------------------
# LLMJudge.evaluate — multiple queries
# ---------------------------------------------------------------------------


class TestLLMJudgeEvaluate:
    async def test_evaluate_aggregates(self):
        settings = _make_settings(llm_provider="openai")
        judge = LLMJudge(settings)

        responses = [
            _good_json(0.9, 0.8, 0.7, "good"),
            _good_json(0.7, 0.6, 0.5, "ok"),
        ]
        call_count = 0

        async def _fake_call(prompt):
            nonlocal call_count
            resp = responses[call_count]
            call_count += 1
            return resp

        judge._call_llm = _fake_call

        report = await judge.evaluate(
            [("q1", ["text1"]), ("q2", ["text2"])],
            doc_id="doc-1",
            concurrency=1,  # sequential to keep call_count deterministic
        )

        assert report.doc_id == "doc-1"
        assert report.total_queries == 2
        assert report.mean_faithfulness == pytest.approx(0.8)
        assert report.mean_relevance == pytest.approx(0.7)
        assert report.mean_completeness == pytest.approx(0.6)
        assert len(report.scores) == 2

    async def test_evaluate_empty(self):
        settings = _make_settings(llm_provider="openai")
        judge = LLMJudge(settings)

        report = await judge.evaluate([], doc_id="empty")

        assert report.total_queries == 0
        assert report.mean_faithfulness == 0.0
        assert report.scores == []


# ---------------------------------------------------------------------------
# LLM error handling
# ---------------------------------------------------------------------------


class TestLLMErrorHandling:
    async def test_bad_json_from_llm_raises(self):
        settings = _make_settings(llm_provider="openai", llm_max_retries=0)
        judge = LLMJudge(settings)
        judge._call_llm = AsyncMock(return_value="This is not JSON at all")

        with pytest.raises(json.JSONDecodeError):
            await judge.score("q", ["text"])

    async def test_timeout_propagates(self):
        settings = _make_settings(llm_provider="openai", llm_max_retries=0)
        judge = LLMJudge(settings)
        judge._call_llm = AsyncMock(side_effect=TimeoutError("request timed out"))

        with pytest.raises(TimeoutError):
            await judge.score("q", ["text"])

    async def test_missing_keys_default_to_zero(self):
        """If the LLM returns JSON but omits some keys, they default to 0."""
        settings = _make_settings(llm_provider="openai")
        judge = LLMJudge(settings)

        partial = json.dumps({"faithfulness": 0.9, "reasoning": "partial"})
        judge._call_llm = AsyncMock(return_value=partial)

        result = await judge.score("q", ["text"])

        assert result.faithfulness == 0.9
        assert result.relevance == 0.0
        assert result.completeness == 0.0


# ---------------------------------------------------------------------------
# evaluate_with_judge integration (mocked searcher + LLM)
# ---------------------------------------------------------------------------


class TestEvaluateWithJudge:
    async def test_integration(self, tmp_path):
        settings = _make_settings(llm_provider="openai", data_dir=str(tmp_path / "data"))

        doc_dir = tmp_path / "data" / "documents" / "test-doc"
        doc_dir.mkdir(parents=True)

        mock_chunks = MagicMock()
        mock_chunks.l3_chunks = []

        mock_search_result = MagicMock()
        mock_search_result.content = "Some relevant text about X."
        mock_search_response = MagicMock()
        mock_search_response.results = [mock_search_result]

        mock_searcher = MagicMock()
        mock_searcher.search = MagicMock(return_value=mock_search_response)

        from ingestible.eval import EvalQuery

        queries = [
            EvalQuery(query="What is X?", expected_chunk_ids=["c1"]),
            EvalQuery(query="How does Y work?", expected_chunk_ids=["c2"]),
        ]

        responses = [
            _good_json(0.9, 0.8, 0.7, "good"),
            _good_json(0.8, 0.7, 0.6, "decent"),
        ]
        call_count = 0

        async def _fake_call_llm(prompt):
            nonlocal call_count
            resp = responses[call_count]
            call_count += 1
            return resp

        with (
            patch("ingestible.eval_llm_judge.load_chunks", return_value=mock_chunks),
            patch("ingestible.eval_llm_judge.Embedder"),
            patch("ingestible.eval_llm_judge.load_searcher", return_value=mock_searcher),
            patch.object(LLMJudge, "_call_llm", side_effect=_fake_call_llm),
        ):
            report = await evaluate_with_judge(
                "test-doc",
                settings,
                queries=queries,
                k=5,
                concurrency=1,
            )

        assert report.doc_id == "test-doc"
        assert report.total_queries == 2
        assert report.mean_faithfulness == pytest.approx(0.85)
        assert report.mean_relevance == pytest.approx(0.75)
        assert report.mean_completeness == pytest.approx(0.65)

    async def test_missing_doc_raises(self, tmp_path):
        settings = _make_settings(data_dir=str(tmp_path / "data"))

        with pytest.raises(FileNotFoundError, match="Document not found"):
            await evaluate_with_judge("no-such-doc", settings)

    async def test_no_queries_and_no_hypothetical_questions_raises(self, tmp_path):
        settings = _make_settings(data_dir=str(tmp_path / "data"))
        doc_dir = tmp_path / "data" / "documents" / "empty-doc"
        doc_dir.mkdir(parents=True)

        mock_chunks = MagicMock()
        mock_chunks.l3_chunks = []

        with (
            patch("ingestible.eval_llm_judge.load_chunks", return_value=mock_chunks),
            patch("ingestible.eval_llm_judge.Embedder"),
            patch("ingestible.eval_llm_judge.load_searcher"),
        ):
            with pytest.raises(ValueError, match="No hypothetical questions"):
                await evaluate_with_judge("empty-doc", settings)
