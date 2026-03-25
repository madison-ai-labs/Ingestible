"""Tests for query expansion techniques (HyDE, sub-question decomposition)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from ingestible.config import Settings
from ingestible.search.query_expansion import (
    HyDEExpander,
    QueryExpansionConfig,
    SubQuestionDecomposer,
    expand_query,
)


def _make_settings(**overrides) -> Settings:
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


def _openai_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


def _anthropic_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.content = [SimpleNamespace(type="text", text=text)]
    return resp


# -- QueryExpansionConfig defaults --


def test_config_defaults():
    config = QueryExpansionConfig()
    assert config.hyde_enabled is False
    assert config.sub_questions_enabled is False
    assert config.max_sub_questions == 3


# -- HyDE with OpenAI --


async def test_hyde_openai():
    settings = _make_settings(llm_provider="openai")

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_openai_response("Hypothetical passage about X.")
    )

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        expander = HyDEExpander(settings)
        result = await expander.expand("What is X?")

    assert result == "Hypothetical passage about X."
    mock_client.chat.completions.create.assert_awaited_once()
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["messages"][0]["content"].startswith("You are a helpful")
    assert call_kwargs["messages"][1]["content"] == "What is X?"


# -- HyDE with Anthropic --


async def test_hyde_anthropic():
    settings = _make_settings(llm_provider="anthropic")

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=_anthropic_response("Anthropic hypothetical passage.")
    )

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        expander = HyDEExpander(settings)
        result = await expander.expand("What is Y?")

    assert result == "Anthropic hypothetical passage."
    mock_client.messages.create.assert_awaited_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["messages"][0]["content"] == "What is Y?"


# -- Sub-question decomposition with OpenAI --


async def test_sub_question_openai():
    settings = _make_settings(llm_provider="openai")

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_openai_response(
            "What is the capital of France?\nWhat is the population of Paris?"
        )
    )

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        decomposer = SubQuestionDecomposer(settings)
        result = await decomposer.decompose("Tell me about Paris")

    assert len(result) == 2
    assert "capital of France" in result[0]
    assert "population of Paris" in result[1]


# -- Sub-question decomposition with Anthropic --


async def test_sub_question_anthropic():
    settings = _make_settings(llm_provider="anthropic")

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=_anthropic_response(
            "What is quantum entanglement?\nHow does entanglement relate to computing?"
        )
    )

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        decomposer = SubQuestionDecomposer(settings)
        result = await decomposer.decompose("Explain quantum computing")

    assert len(result) == 2
    assert "quantum entanglement" in result[0]


# -- Sub-question max_sub_questions truncation --


async def test_sub_question_truncation():
    settings = _make_settings(llm_provider="openai")

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_openai_response("Q1?\nQ2?\nQ3?\nQ4?\nQ5?")
    )

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        decomposer = SubQuestionDecomposer(settings)
        result = await decomposer.decompose("Big question", max_sub_questions=2)

    assert len(result) == 2


# -- expand_query: no expansion --


async def test_expand_query_no_expansion():
    settings = _make_settings()
    config = QueryExpansionConfig()
    result = await expand_query("simple query", config, settings)
    assert result == ["simple query"]


# -- expand_query: HyDE enabled --


async def test_expand_query_hyde():
    settings = _make_settings(llm_provider="openai")
    config = QueryExpansionConfig(hyde_enabled=True)

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_openai_response("A generated passage.")
    )

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        result = await expand_query("What is X?", config, settings)

    assert len(result) == 1
    assert result[0] == "A generated passage."


# -- expand_query: sub-questions enabled --


async def test_expand_query_sub_questions():
    settings = _make_settings(llm_provider="openai")
    config = QueryExpansionConfig(sub_questions_enabled=True)

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_openai_response("Sub Q1?\nSub Q2?")
    )

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        result = await expand_query("Complex question", config, settings)

    assert len(result) == 2
    assert result[0] == "Sub Q1?"
    assert result[1] == "Sub Q2?"


# -- expand_query: both HyDE and sub-questions --


async def test_expand_query_both():
    settings = _make_settings(llm_provider="openai")
    config = QueryExpansionConfig(hyde_enabled=True, sub_questions_enabled=True)

    hyde_response = _openai_response("Hyde passage.")
    sub_q_response = _openai_response("Sub A?\nSub B?")

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=[hyde_response, sub_q_response])

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        result = await expand_query("Complex Q", config, settings)

    assert "Hyde passage." in result
    assert "Sub A?" in result
    assert "Sub B?" in result


# -- expand_query: HyDE failure falls back to raw query --


async def test_expand_query_hyde_failure_fallback():
    settings = _make_settings(llm_provider="openai")
    config = QueryExpansionConfig(hyde_enabled=True)

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        result = await expand_query("fallback query", config, settings)

    assert result == ["fallback query"]
