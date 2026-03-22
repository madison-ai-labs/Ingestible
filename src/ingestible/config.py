from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class TomlConfigSource(PydanticBaseSettingsSource):
    """Load settings from ./ingestible.toml or ~/.config/ingestible/config.toml."""

    PATHS = [
        Path("ingestible.toml"),
        Path.home() / ".config" / "ingestible" / "config.toml",
    ]

    def __init__(self, settings_cls: type[BaseSettings]):
        super().__init__(settings_cls)
        self._data: dict[str, Any] = {}
        # Local file wins over user-level
        for p in self.PATHS:
            if p.is_file():
                with open(p, "rb") as f:
                    self._data = tomllib.load(f)
                break

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        val = self._data.get(field_name)
        return val, field_name, val is None

    def __call__(self) -> dict[str, Any]:
        return {k: v for k, v in self._data.items() if v is not None}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INGEST_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ):
        # Priority: init > env > dotenv > TOML > defaults
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSource(settings_cls),
            file_secret_settings,
        )

    # LLM provider
    llm_provider: Literal["openai", "anthropic"] = "anthropic"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"
    llm_concurrency: int = 10

    # LLM resilience
    llm_timeout: int = 120  # seconds per LLM call
    llm_max_retries: int = 3
    llm_retry_base_delay: float = 1.0

    # Embedding
    embedding_provider: Literal["local", "openai", "cohere", "voyage"] = "local"
    embedding_model: str = "intfloat/e5-large-v2"
    embedding_dimensions: int | None = None
    embedding_quantization: Literal["none", "binary"] = "none"
    embedding_device: str = "auto"
    # API keys for embedding providers (only needed if embedding_provider != "local")
    openai_embedding_api_key: str = ""  # falls back to openai_api_key if empty
    cohere_api_key: str = ""
    voyage_api_key: str = ""

    # CORS
    cors_origins: list[str] = Field(default=["*"])

    # Storage
    data_dir: Path = Path("data")
    min_disk_space_mb: int = 500  # minimum free disk space in MB for readiness

    # Rate limiting (requests per minute)
    rate_limit_ingest: str = "10/minute"
    rate_limit_search: str = "60/minute"
    rate_limit_default: str = "120/minute"

    # Limits
    max_upload_bytes: int = 500_000_000  # 500 MB
    max_concurrent_ingestions: int = 2
    max_total_llm_concurrency: int = 20  # hard ceiling across all parallel workers
    parse_timeout: int = 300  # seconds (5 min max for parsing)

    # Cleaning
    cleaning_enabled: bool = True

    # Chunking
    max_chunk_tokens: int = 500
    min_chunk_tokens: int = 100
    chunk_overlap_fraction: float = 0.1
    chunking_strategy: Literal["paragraph", "semantic", "recursive", "docling", "code"] = (
        "paragraph"
    )
    semantic_threshold_percentile: int = 10
    contextual_chunking: bool = False

    # Extraction profile
    extraction_profile: str = "auto"  # "auto", "paper", "article", "documentation", "general"
    profile_llm_fallback: bool = False  # Use LLM to classify ambiguous documents

    # Audio/video transcription
    whisper_model: str = "base"  # faster-whisper model: tiny, base, small, medium, large-v3

    # Knowledge graph
    extract_knowledge_graph: bool = False

    # Content classification
    content_classification: bool = False  # classify content blocks into tiers (T0-T3)

    # Dedup
    dedup_enabled: bool = True

    # Checkpoint
    checkpoint_enabled: bool = True

    # Logging
    log_json: bool = True  # JSON structured logging (False for console dev output)
    log_level: str = "INFO"

    # Access control
    access_control_enabled: bool = False  # enable per-document access filtering

    # Audit
    audit_enabled: bool = False  # log search queries to data/audit.jsonl

    # Sparse retrieval
    sparse_retrieval: Literal["bm25", "splade"] = "bm25"  # sparse retrieval backend
    splade_model: str = "naver/splade-cocondenser-ensembledistil"

    # Search
    searcher_cache_size: int = 50  # max cached document searchers in memory
    vector_weight: float = 0.4
    bm25_weight: float = 0.6
    exact_match_boost: float = 0.003  # per-term bonus for verbatim query term matches
    default_search_results: int = 5
    reranker_model: str = ""
    reranker_top_k: int = 50
    reranker_weight: float = 0.5
    pinned_top_n: int = 3  # chunks per pinned document to always include in corpus search

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"


def get_settings(**overrides) -> Settings:
    return Settings(**overrides)
