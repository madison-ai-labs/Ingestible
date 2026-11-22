"""Endpoint test for POST /ancs/ingest.

Proves the HTTP wiring routes a document into the ANCS tenant chosen by
PROVENANCE (source_channel), refuses unprovisioned classes, and never lets the
upload content pick the tier. The heavy pipeline + the ANCS HTTP call are mocked.

Run with:  pytest tests/test_ancs_endpoint.py -v
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

import ingestible.adapters.ancs_export as ancs_export_mod
import ingestible.api as api_mod
from ingestible.config import Settings


class _FakeChunks:
    doc_id = "doc-1"
    l0 = None  # unused — export is mocked


@pytest.fixture
def client_and_capture(tmp_path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path,
        ancs_url="http://ancs.local",
        ancs_key_personal="PERSONAL_KEY",
        ancs_key_untrusted="UNTRUSTED_KEY",
        ancs_key_reference="",  # deliberately unprovisioned
    )
    monkeypatch.setattr(api_mod, "_settings", settings)

    # Stub the pipeline: don't actually parse/enrich/embed.
    monkeypatch.setattr(api_mod, "ingest", lambda *a, **k: tmp_path / "doc-1")
    monkeypatch.setattr(api_mod, "load_document_meta", lambda d: {"doc_id": "doc-1"})
    monkeypatch.setattr(api_mod, "load_chunks", lambda d: _FakeChunks())
    monkeypatch.setattr(api_mod, "_check_upload_size", lambda *a, **k: None)
    monkeypatch.setattr(api_mod, "_check_ingestion_quotas", lambda *a, **k: False)

    captured: dict = {}

    def fake_export(chunks, cfg):
        captured["api_key"] = cfg.api_key
        captured["base_url"] = cfg.base_url
        captured["source_uri"] = cfg.source_uri
        return ancs_export_mod.ANCSIngestResult(
            doc_id="doc-1",
            memory_items_created=3,
            entities_created=2,
            hyperedges_created=4,
            kg_triples_ingested=2,
        )

    monkeypatch.setattr(ancs_export_mod, "export_to_ancs", fake_export)

    return TestClient(api_mod.app), captured


def _post(client, channel: str):
    return client.post(
        "/ancs/ingest",
        files={
            "file": (
                "memo.txt",
                io.BytesIO(b"The Helios reactor powers the Aurora grid."),
                "text/plain",
            )
        },
        data={"source_channel": channel},
    )


def test_user_authored_routes_to_personal_tenant(client_and_capture):
    client, captured = client_and_capture
    r = _post(client, "user_authored")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trust_class"] == "personal"
    assert body["can_promote"] is True
    assert body["kg_triples_ingested"] == 2
    assert captured["api_key"] == "PERSONAL_KEY"
    assert captured["source_uri"] == "ingestible://personal/doc-1"


def test_unknown_provenance_defaults_to_untrusted_tenant(client_and_capture):
    client, captured = client_and_capture
    r = _post(client, "totally-made-up-channel")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trust_class"] == "untrusted"
    assert body["can_promote"] is False
    assert captured["api_key"] == "UNTRUSTED_KEY"


def test_unprovisioned_class_is_refused(client_and_capture):
    client, _ = client_and_capture
    # 'download' → reference, whose key is unset → refuse, don't fall back.
    r = _post(client, "download")
    assert r.status_code == 503
    assert "reference" in r.json()["detail"]
