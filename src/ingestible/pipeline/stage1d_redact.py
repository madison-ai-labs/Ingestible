"""Stage 1d — PII Redaction.

Runs after Stage 1b (clean) on the ParsedDocument markdown text.
Requires the `redaction` optional extra:
    pip install "ingestible[redaction]"
    python -m spacy download en_core_web_sm   # English
    python -m spacy download de_core_news_sm  # German (optional)

Three modes:
  placeholder   — PERSON → [PERSON], EMAIL → [EMAIL_ADDRESS], etc.
  pseudonymize  — consistent fictional labels within the document
                  (Person A, Person B, Location 1 …). Structured PII
                  (emails, phones, IBANs) still use placeholder.
  suppress      — all entities → [REDACTED] (no type info)

Language handling:
  NER-based entity types (PERSON, LOCATION, ORG, NRP) require a spaCy model
  for the document's language. When no model is available, those types are
  skipped and only regex-based recognizers run (emails, phones, IBANs, etc.).
  This prevents false positives from feeding non-English text through the
  English NER model.
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
# Entity type classification
# ---------------------------------------------------------------------------

# Require a language-specific NER model
_NER_ENTITY_TYPES: frozenset[str] = frozenset({"PERSON", "LOCATION", "ORG", "NRP"})

# Handled by regex — language-independent
_REGEX_ENTITY_TYPES: frozenset[str] = frozenset({
    "EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE", "CREDIT_CARD",
    "DATE_TIME", "US_SSN", "US_PASSPORT", "IP_ADDRESS", "URL",
    "MEDICAL_LICENSE",
})

# spaCy NER labels that are not PII — suppress from results
_NER_LABELS_TO_IGNORE: list[str] = [
    "CARDINAL", "MONEY", "QUANTITY", "ORDINAL", "PERCENT",
    "PRODUCT", "WORK_OF_ART", "EVENT", "LAW", "LANGUAGE",
    "TIME", "FAC",
]

# ISO 639-1 language code → spaCy model name
_SPACY_MODELS: dict[str, str] = {
    "en": "en_core_web_sm",
    "de": "de_core_news_sm",
    "es": "es_core_news_sm",
    "fr": "fr_core_news_sm",
    "it": "it_core_news_sm",
    "nl": "nl_core_news_sm",
    "pt": "pt_core_news_sm",
}

# Minimum Presidio confidence score to accept an NER hit.
# Regex recognizers always return 1.0; this threshold only affects NER.
_MIN_NER_SCORE: float = 0.75

# ---------------------------------------------------------------------------
# Entity types that get consistent pseudonyms in pseudonymize mode
# ---------------------------------------------------------------------------

_PSEUDONYMIZABLE: frozenset[str] = frozenset({"PERSON", "LOCATION", "ORG", "NRP"})

_PSEUDO_LABELS: dict[str, list[str]] = {
    "PERSON": [f"Person {c}" for c in string.ascii_uppercase],
    "LOCATION": [f"Location {i}" for i in range(1, 27)],
    "ORG": [f"Organization {c}" for c in string.ascii_uppercase],
    "NRP": [f"Group {c}" for c in string.ascii_uppercase],
}
_PSEUDO_FALLBACK = "Entity {n}"

# ---------------------------------------------------------------------------
# Lazy-initialised Presidio analyzer (loading spaCy is expensive)
# Cache key: (sorted entity types, language)
# ---------------------------------------------------------------------------
_analyzer_cache: dict[tuple, object] = {}


def _get_analyzer(entity_types: list[str], language: str = "en"):
    """Return a cached AnalyzerEngine for the given language.

    When the requested language has no available spaCy model, NER-based
    entity types are dropped from the active set and only regex recognizers
    run. Returns (analyzer, active_entity_types, analyzer_language).
    """
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
    except ImportError as e:
        raise ImportError(
            "presidio-analyzer is required for redaction. "
            "Install with: pip install 'ingestible[redaction]'"
        ) from e

    lang = language[:2].lower()  # normalise "en-US" → "en"
    model_name = _SPACY_MODELS.get(lang)
    cache_key = (tuple(sorted(entity_types)), lang)

    if cache_key in _analyzer_cache:
        return _analyzer_cache[cache_key]

    # Determine which entity types are actually usable
    ner_requested = [t for t in entity_types if t in _NER_ENTITY_TYPES]
    regex_requested = [t for t in entity_types if t in _REGEX_ENTITY_TYPES]

    nlp_engine = None
    analyzer_lang = lang
    active_ner_types = ner_requested

    if ner_requested and model_name:
        try:
            provider = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": lang, "model_name": model_name}],
            })
            nlp_engine = provider.create_engine()
            logger.debug("Loaded spaCy model %s for language '%s'", model_name, lang)
        except OSError:
            logger.warning(
                "spaCy model '%s' not found — NER redaction disabled for language '%s'. "
                "Install with: python -m spacy download %s",
                model_name, lang, model_name,
            )
            nlp_engine = None
            active_ner_types = []
        except Exception as e:
            logger.warning("Failed to load NER model for '%s': %s. Falling back to regex.", lang, e)
            nlp_engine = None
            active_ner_types = []
    elif ner_requested and not model_name:
        logger.warning(
            "No spaCy model configured for language '%s' — "
            "PERSON/LOCATION/ORG redaction skipped. "
            "Regex-based types (%s) will still run.",
            lang,
            ", ".join(regex_requested) or "none",
        )
        active_ner_types = []

    # Always analyze as "en" for regex recognizers when language has no model,
    # since Presidio's regex recognizers are language-tagged "en" by default.
    if nlp_engine:
        analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=[lang])
        analyzer_lang = lang
    else:
        analyzer = AnalyzerEngine(supported_languages=["en"])
        analyzer_lang = "en"

    active_types = active_ner_types + regex_requested
    _analyzer_cache[cache_key] = (analyzer, active_types, analyzer_lang)
    return analyzer, active_types, analyzer_lang


# ---------------------------------------------------------------------------
# Core redaction logic
# ---------------------------------------------------------------------------

def _normalize_entity_key(text: str) -> str:
    """Canonical key for entity de-duplication.

    Strips possessive suffixes and trailing punctuation so that
    'Alice Johnson' and "Alice Johnson's" resolve to the same entry.
    """
    import re
    normalized = re.sub(r"['\u2019]s$", "", text.strip())
    return normalized.rstrip(".,;:!?").lower()


def _build_pseudonym_map(
    entity_texts_by_type: dict[str, list[str]],
) -> dict[str, str]:
    """Assign consistent labels to unique entities across the document."""
    mapping: dict[str, str] = {}
    counters: dict[str, int] = {}

    for entity_type, texts in entity_texts_by_type.items():
        labels = _PSEUDO_LABELS.get(entity_type, [])
        for text in texts:
            key = _normalize_entity_key(text)
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
        key = _normalize_entity_key(text)
        return pseudonym_map.get(key, f"[{entity_type}]")
    return f"[{entity_type}]"


def _filter_results(results: list, active_types: list[str]) -> list:
    """Keep only results matching active entity types and above confidence threshold."""
    active_set = set(active_types)
    out = []
    for r in results:
        if r.entity_type not in active_set:
            continue
        # Apply minimum confidence threshold to NER results only
        if r.entity_type in _NER_ENTITY_TYPES and r.score < _MIN_NER_SCORE:
            continue
        out.append(r)
    return out


def _apply_redactions(
    text: str,
    results: list,
    mode: str,
    pseudonym_map: dict[str, str],
    active_types: list[str],
    page_num: int,
) -> tuple[str, list[RedactedEntity]]:
    """Apply analyzer results to text, replacing spans right-to-left."""
    filtered = _filter_results(results, active_types)
    sorted_results = sorted(filtered, key=lambda r: r.start, reverse=True)
    entities: list[RedactedEntity] = []

    for result in sorted_results:
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

    Uses the document's detected_language to load the appropriate spaCy model.
    When no model is available for the document language, NER-based types
    (PERSON, LOCATION, ORG) are skipped; regex-based types always run.

    Returns the modified ParsedDocument and a RedactionManifest recording
    every substitution made.
    """
    mode: str = settings.redaction_mode
    entity_types: list[str] = list(settings.redaction_entities)
    # redaction_language override takes priority over auto-detected language;
    # fallback to doc.detected_language then "en" if neither is set.
    language: str = settings.redaction_language or doc.detected_language or "en"
    doc_id = doc.source_path  # overwritten with real doc_id by Stage 6

    analyzer, active_types, analyzer_lang = _get_analyzer(entity_types, language)

    if not active_types:
        logger.warning("No active entity types for language '%s' — redaction is a no-op", language)
        manifest = RedactionManifest(
            doc_id=doc_id,
            mode=mode,
            entity_types=entity_types,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        return doc, manifest

    all_entities: list[RedactedEntity] = []

    if mode == "pseudonymize":
        # First pass: collect all entities per type to build consistent map
        texts_by_type: dict[str, list[str]] = {t: [] for t in _PSEUDONYMIZABLE}
        for page in doc.pages:
            if not page.markdown:
                continue
            results = analyzer.analyze(
                text=page.markdown, language=analyzer_lang, entities=active_types
            )
            for r in _filter_results(results, active_types):
                if r.entity_type in _PSEUDONYMIZABLE:
                    original = page.markdown[r.start:r.end]
                    key = _normalize_entity_key(original)
                    bucket = texts_by_type.setdefault(r.entity_type, [])
                    if key not in [_normalize_entity_key(t) for t in bucket]:
                        bucket.append(original)

        pseudonym_map = _build_pseudonym_map(texts_by_type)

        # Second pass: apply replacements
        for page in doc.pages:
            if not page.markdown:
                continue
            results = analyzer.analyze(
                text=page.markdown, language=analyzer_lang, entities=active_types
            )
            page.markdown, page_entities = _apply_redactions(
                page.markdown, results, mode, pseudonym_map, active_types, page.page_num
            )
            all_entities.extend(page_entities)

    else:
        pseudonym_map = {}
        for page in doc.pages:
            if not page.markdown:
                continue
            results = analyzer.analyze(
                text=page.markdown, language=analyzer_lang, entities=active_types
            )
            page.markdown, page_entities = _apply_redactions(
                page.markdown, results, mode, {}, active_types, page.page_num
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
            "Redacted %d entities (%s mode, lang=%s) across %d pages",
            len(all_entities),
            mode,
            language,
            len(doc.pages),
        )
    else:
        logger.info("Redaction scan complete — no entities found (lang=%s)", language)

    return doc, manifest
