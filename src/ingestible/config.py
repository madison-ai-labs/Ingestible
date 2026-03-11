from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INGEST_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM provider
    llm_provider: Literal["openai", "anthropic"] = "anthropic"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"
    llm_concurrency: int = 10

    # Embedding
    embedding_model: str = "intfloat/e5-large-v2"

    # Storage
    data_dir: Path = Path("data")

    # Cleaning
    cleaning_enabled: bool = True

    # Chunking
    max_chunk_tokens: int = 500
    min_chunk_tokens: int = 100
    chunk_overlap_fraction: float = 0.1
    chunking_strategy: Literal["paragraph", "semantic", "recursive"] = "paragraph"
    semantic_threshold_percentile: int = 10
    contextual_chunking: bool = False

    # Dedup
    dedup_enabled: bool = True

    # Search
    vector_weight: float = 0.7
    bm25_weight: float = 0.3
    default_search_results: int = 5
    reranker_model: str = ""
    reranker_top_k: int = 50
    reranker_weight: float = 0.5

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"


def get_settings(**overrides) -> Settings:
    return Settings(**overrides)
