"""WP 7.2 — TOML Config File Support.

Tests the TomlConfigSource integration with pydantic-settings.
Verifies priority: env vars > TOML > defaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ingestible.config import Settings, TomlConfigSource


class TestTomlConfigSource:
    def test_loads_from_toml_file(self, tmp_path, monkeypatch):
        toml_path = tmp_path / "ingestible.toml"
        toml_path.write_text(
            'data_dir = "custom_data"\n'
            "max_chunk_tokens = 300\n"
            'chunking_strategy = "recursive"\n'
        )

        # Patch TomlConfigSource.PATHS to point at our temp file
        monkeypatch.setattr(TomlConfigSource, "PATHS", [toml_path])
        # Clear env vars that might interfere
        monkeypatch.delenv("INGEST_DATA_DIR", raising=False)
        monkeypatch.delenv("INGEST_MAX_CHUNK_TOKENS", raising=False)
        monkeypatch.delenv("INGEST_CHUNKING_STRATEGY", raising=False)

        settings = Settings()

        assert str(settings.data_dir) == "custom_data"
        assert settings.max_chunk_tokens == 300
        assert settings.chunking_strategy == "recursive"

    def test_env_var_overrides_toml(self, tmp_path, monkeypatch):
        toml_path = tmp_path / "ingestible.toml"
        toml_path.write_text('data_dir = "from_toml"\n')

        monkeypatch.setattr(TomlConfigSource, "PATHS", [toml_path])
        monkeypatch.setenv("INGEST_DATA_DIR", "from_env")

        settings = Settings()

        # Env var wins over TOML
        assert str(settings.data_dir) == "from_env"

    def test_init_overrides_everything(self, tmp_path, monkeypatch):
        toml_path = tmp_path / "ingestible.toml"
        toml_path.write_text('data_dir = "from_toml"\n')

        monkeypatch.setattr(TomlConfigSource, "PATHS", [toml_path])
        monkeypatch.setenv("INGEST_DATA_DIR", "from_env")

        settings = Settings(data_dir=Path("from_init"))

        # Init kwarg wins over everything
        assert str(settings.data_dir) == "from_init"

    def test_defaults_when_no_toml(self, tmp_path, monkeypatch):
        # Point at nonexistent file
        monkeypatch.setattr(TomlConfigSource, "PATHS", [tmp_path / "nope.toml"])
        monkeypatch.delenv("INGEST_DATA_DIR", raising=False)

        settings = Settings()

        # Should use default
        assert str(settings.data_dir) == "data"
        assert settings.max_chunk_tokens == 500

    def test_local_toml_wins_over_user_level(self, tmp_path, monkeypatch):
        local = tmp_path / "local" / "ingestible.toml"
        local.parent.mkdir()
        local.write_text("max_chunk_tokens = 111\n")

        user = tmp_path / "user" / "config.toml"
        user.parent.mkdir()
        user.write_text("max_chunk_tokens = 999\n")

        monkeypatch.setattr(TomlConfigSource, "PATHS", [local, user])
        monkeypatch.delenv("INGEST_MAX_CHUNK_TOKENS", raising=False)

        settings = Settings()

        # Local file wins (first in PATHS list)
        assert settings.max_chunk_tokens == 111

    def test_toml_partial_override(self, tmp_path, monkeypatch):
        """TOML only overrides specified keys, rest stay default."""
        toml_path = tmp_path / "ingestible.toml"
        toml_path.write_text("vector_weight = 0.9\n")

        monkeypatch.setattr(TomlConfigSource, "PATHS", [toml_path])
        monkeypatch.delenv("INGEST_VECTOR_WEIGHT", raising=False)
        monkeypatch.delenv("INGEST_BM25_WEIGHT", raising=False)

        settings = Settings()

        assert settings.vector_weight == 0.9
        assert settings.bm25_weight == 0.3  # default unchanged


class TestConfigCLI:
    def test_config_command_outputs_settings(self, capsys, monkeypatch):
        monkeypatch.setattr(TomlConfigSource, "PATHS", [])
        monkeypatch.delenv("INGEST_DATA_DIR", raising=False)

        from ingestible.cli import main

        main(["config"])

        output = capsys.readouterr().out
        assert "data_dir=" in output
        assert "max_chunk_tokens=" in output
        assert "llm_provider=" in output
