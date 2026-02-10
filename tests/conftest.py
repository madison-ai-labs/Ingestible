from __future__ import annotations

from pathlib import Path

import pytest

from ingestion_tool.config import Settings


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def settings(tmp_data_dir: Path) -> Settings:
    return Settings(
        data_dir=tmp_data_dir,
        llm_provider="openai",
        openai_api_key="test-key",
        embedding_model="intfloat/e5-large-v2",
    )
