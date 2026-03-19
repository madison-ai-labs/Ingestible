from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal

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

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
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

    # Embedding
    embedding_model: str = "intfloat/e5-large-v2"
    embedding_dimensions: int | None = None  # Matryoshka truncation (None = full)
    embedding_quantization: Literal["none", "binary"] = "none"

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

    # Extraction profile
    extraction_profile: str = "auto"  # "auto", "paper", "article", "documentation", "general"
    profile_llm_fallback: bool = False  # Use LLM to classify ambiguous documents

    # Dedup
    dedup_enabled: bool = True

    # Checkpoint
    checkpoint_enabled: bool = True

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
