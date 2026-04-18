"""Stage 1d — PII Redaction.

Runs after Stage 1b (clean) on the ParsedDocument markdown text.
Requires the `redaction` optional extra:
    pip install "ingestible[redaction]"
    python -m spacy download en_core_web_sm

Three modes:
  placeholder   — PERSON → [PERSON], EMAIL → [EMAIL_ADDRESS], etc.
  pseudonymize  — consistent fictional labels within the document
                  (Person A, Person B, Location 1 …). Structured PII
                  (emails, phones, IBANs) still use placeholder.
  suppress      — all entities → [REDACTED] (no type info)
"""

from __future__ import annotations

import logging
import string
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ingestible.models.document import ParsedDocument
from ingestible.models.redaction import RedactedEntity, RedactionManifest

if TYPE_CHECKING:
    from ingestible.config import Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Entity types that benefit from consistent pseudonyms in pseudonymize mode.
# Structured PII (emails, phones, etc.) always get placeholder treatment.
# ---------------------------------------------------------------------------
_PSEUDONYMIZABLE = {"PERSON", "LOCATION", "ORG", "NRP"}

# Labels used for pseudonymization, indexed by entity type
_PSEUDO_LABELS: dict[str, list[str]] = {
    "PERSON": [f"Person {c}" for c in string.ascii_uppercase],
    "LOCATION": [f"Location {i}" for i in range(1, 27)],
    "ORG": [f"Organization {c}" for c in string.ascii_uppercase],
    "NRP": [f"Group {c}" for c in string.ascii_uppercase],
}
_PSEUDO_FALLBACK = "Entity {n}"

# ---------------------------------------------------------------------------
# Lazy-initialised Presidio analyzer (loading spaCy model is expensive)
# ---------------------------------------------------------------------------
_analyzer = None
_analyzer_entities: tuple[str, ...] | None = None


def _get_analyzer(entity_types: list[str]):
    """Return a cached AnalyzerEngine, re-creating if entity list changed."""
    global _analyzer, _analyzer_entities

    current = tuple(sorted(entity_types))
    if _analyzer is not None and _analyzer_entities == current:
        return _analyzer

    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
    except ImportError as e:
        raise ImportError(
            "presidio-analyzer is required for redaction. "
            "Install with: pip install 'ingestible[redaction]'"
        ) from e

    try:
        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        })
        nlp_engine = provider.create_engine()
    except OSError:
        logger.warning(
            "spaCy model 'en_core_web_sm' not found — "
            "falling back to regex-only recognizers. "
            "Run: python -m spacy download en_core_web_sm"
        )
        nlp_engine = None

    if nlp_engine:
        _analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
    else:
        _analyzer = AnalyzerEngine(supported_languages=["en"])

    _analyzer_entities = current
    return _analyzer


# ---------------------------------------------------------------------------
# Core redaction logic
# ---------------------------------------------------------------------------

def _build_pseudonym_map(
    entity_texts_by_type: dict[str, list[str]],
) -> dict[str, str]:
    """Assign consistent labels to unique entities across the document."""
    mapping: dict[str, str] = {}
    counters: dict[str, int] = {}

    for entity_type, texts in entity_texts_by_type.items():
        labels = _PSEUDO_LABELS.get(entity_type, [])
        for text in texts:
            key = text.lower()
            if key in mapping:
                continue
            idx = counters.get(entity_type, 0)
            if idx < len(labels):
                mapping[key] = labels[idx]
            else:
                mapping[key] = _PSEUDO_FALLBACK.format(n=idx + 1)
            counters[entity_type] = idx + 1

    return mapping


def _replacement(
    text: str,
    entity_type: str,
    mode: str,
    pseudonym_map: dict[str, str],
) -> str:
    if mode == "suppress":
        return "[REDACTED]"
    if mode == "pseudonymize" and entity_type in _PSEUDONYMIZABLE:
        return pseudonym_map.get(text.lower(), f"[{entity_type}]")
    return f"[{entity_type}]"


def _apply_redactions(
    text: str,
    results: list,
    mode: str,
    pseudonym_map: dict[str, str],
    entity_types: list[str],
    page_num: int,
) -> tuple[str, list[RedactedEntity]]:
    """Apply analyzer results to text, replacing spans right-to-left."""
    # Sort descending by start so offsets stay valid as we replace
    sorted_results = sorted(results, key=lambda r: r.start, reverse=True)
    entities: list[RedactedEntity] = []

    for result in sorted_results:
        if result.entity_type not in entity_types:
            continue
        original = text[result.start:result.end]
        repl = _replacement(original, result.entity_type, mode, pseudonym_map)
        text = text[: result.start] + repl + text[result.end:]
        entities.append(
            RedactedEntity(
                entity_type=result.entity_type,
                original=original,
                replacement=repl,
                page_num=page_num,
            )
        )

    return text, entities


def redact_document(
    doc: ParsedDocument,
    settings: "Settings",
) -> tuple[ParsedDocument, RedactionManifest]:
    """Scan each page's markdown for PII and redact in-place.

    Returns the modified ParsedDocument and a RedactionManifest recording
    every substitution made. The manifest is saved separately by Stage 6
    and is access-gated.
    """
    mode: str = settings.redaction_mode
    entity_types: list[str] = list(settings.redaction_entities)
    doc_id = doc.source_path  # will be overwritten with real doc_id by caller

    analyzer = _get_analyzer(entity_types)

    all_entities: list[RedactedEntity] = []

    # --- Pseudonymize: two-pass (collect then replace) ---
    if mode == "pseudonymize":
        # First pass: collect all entities per type
        texts_by_type: dict[str, list[str]] = {t: [] for t in _PSEUDONYMIZABLE}
        for page in doc.pages:
            if not page.markdown:
                continue
            results = analyzer.analyze(text=page.markdown, language="en", entities=entity_types)
            for r in results:
                if r.entity_type in _PSEUDONYMIZABLE:
                    original = page.markdown[r.start:r.end]
                    key = original.lower()
                    bucket = texts_by_type.setdefault(r.entity_type, [])
                    if key not in [t.lower() for t in bucket]:
                        bucket.append(original)

        pseudonym_map = _build_pseudonym_map(texts_by_type)

        # Second pass: apply replacements
        for page in doc.pages:
            if not page.markdown:
                continue
            results = analyzer.analyze(text=page.markdown, language="en", entities=entity_types)
            page.markdown, page_entities = _apply_redactions(
                page.markdown, results, mode, pseudonym_map, entity_types, page.page_num
            )
            all_entities.extend(page_entities)

    else:
        pseudonym_map = {}
        for page in doc.pages:
            if not page.markdown:
                continue
            results = analyzer.analyze(text=page.markdown, language="en", entities=entity_types)
            page.markdown, page_entities = _apply_redactions(
                page.markdown, results, mode, {}, entity_types, page.page_num
            )
            all_entities.extend(page_entities)

    manifest = RedactionManifest(
        doc_id=doc_id,
        mode=mode,
        entity_types=entity_types,
        entities=all_entities,
        pseudonym_map=pseudonym_map,
        total_redactions=len(all_entities),
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    if all_entities:
        logger.info(
            "Redacted %d entities (%s mode) across %d pages",
            len(all_entities),
            mode,
            len(doc.pages),
        )
    else:
        logger.info("Redaction scan complete — no entities found")

    return doc, manifest
