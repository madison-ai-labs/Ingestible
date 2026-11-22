"""Tests for Stage 1d PII redaction quality.

Covers:
- Correct detection of each entity type in English text
- Placeholder, pseudonymize, and suppress modes
- Pseudonym consistency within a document
- No false positives on non-PII text
- Language isolation: German text does not produce false positives via English NER
- Manifest correctness
- No enrichment/embedding changes when redaction is off
"""

from __future__ import annotations

import pytest

from ingestible.config import Settings
from ingestible.models.document import PageContent, ParsedDocument
from ingestible.pipeline.stage1d_redact import _analyzer_cache, redact_document


def _doc(*pages: str, language: str = "en") -> ParsedDocument:
    """Build a minimal ParsedDocument from page strings."""
    return ParsedDocument(
        title="Test",
        source_path="test.txt",
        detected_language=language,
        pages=[PageContent(page_num=i + 1, markdown=text) for i, text in enumerate(pages)],
    )


def _settings(**kwargs) -> Settings:
    return Settings(
        redaction_enabled=True,
        redaction_mode=kwargs.pop("redaction_mode", "placeholder"),
        redaction_entities=kwargs.pop(
            "redaction_entities",
            [
                "PERSON",
                "EMAIL_ADDRESS",
                "PHONE_NUMBER",
                "IBAN_CODE",
                "CREDIT_CARD",
                "DATE_TIME",
                "LOCATION",
            ],
        ),
        **kwargs,
    )


@pytest.fixture(autouse=True)
def clear_analyzer_cache():
    """Ensure each test gets a fresh analyzer so language/entity changes take effect."""
    _analyzer_cache.clear()
    yield
    _analyzer_cache.clear()


# ---------------------------------------------------------------------------
# Dependency guard — skip all tests if Presidio is not installed
# ---------------------------------------------------------------------------

presidio_available = False
try:
    import presidio_analyzer  # noqa: F401

    presidio_available = True
except ImportError:
    pass

pytestmark = pytest.mark.skipif(
    not presidio_available,
    reason="presidio-analyzer not installed — run: pip install 'ingestible[redaction]'",
)


# ---------------------------------------------------------------------------
# Placeholder mode — entity detection
# ---------------------------------------------------------------------------


class TestPlaceholderMode:
    def test_email_redacted(self):
        doc = _doc("Contact us at john.doe@example.com for support.")
        _, manifest = redact_document(doc, _settings())
        assert "[EMAIL_ADDRESS]" in doc.pages[0].markdown
        assert "john.doe@example.com" not in doc.pages[0].markdown
        assert any(e.entity_type == "EMAIL_ADDRESS" for e in manifest.entities)

    def test_phone_redacted(self):
        doc = _doc("Call +1 650-555-0199 to reach the office.")
        _, manifest = redact_document(doc, _settings())
        assert "[PHONE_NUMBER]" in doc.pages[0].markdown
        assert "650-555-0199" not in doc.pages[0].markdown

    def test_person_name_redacted(self):
        doc = _doc("The report was signed by Alice Johnson.")
        _, manifest = redact_document(doc, _settings())
        assert "Alice Johnson" not in doc.pages[0].markdown
        assert any(e.entity_type == "PERSON" for e in manifest.entities)

    def test_iban_redacted(self):
        doc = _doc("Please transfer to DE89 3704 0044 0532 0130 00.")
        _, manifest = redact_document(doc, _settings())
        assert "DE89" not in doc.pages[0].markdown
        assert "[IBAN_CODE]" in doc.pages[0].markdown

    def test_replacement_format(self):
        doc = _doc("Email: test@corp.com")
        _, manifest = redact_document(doc, _settings())
        assert "[EMAIL_ADDRESS]" in doc.pages[0].markdown
        entity = next(e for e in manifest.entities if e.entity_type == "EMAIL_ADDRESS")
        assert entity.original == "test@corp.com"
        assert entity.replacement == "[EMAIL_ADDRESS]"

    def test_clean_text_unchanged(self):
        text = "The quarterly report covers revenue trends."
        doc = _doc(text)
        _, manifest = redact_document(
            doc,
            _settings(redaction_entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE"]),
        )
        assert doc.pages[0].markdown == text
        assert manifest.total_redactions == 0

    def test_multiple_entities_same_page(self):
        doc = _doc("Alice Smith, alice@example.com, +1-800-555-0100")
        _, manifest = redact_document(doc, _settings())
        types_found = {e.entity_type for e in manifest.entities}
        assert "EMAIL_ADDRESS" in types_found
        assert "PHONE_NUMBER" in types_found
        assert "alice@example.com" not in doc.pages[0].markdown

    def test_manifest_total_matches_entities(self):
        doc = _doc("Send invoice to bob@example.com or carol@corp.org.")
        _, manifest = redact_document(doc, _settings())
        assert manifest.total_redactions == len(manifest.entities)

    def test_manifest_mode_recorded(self):
        doc = _doc("test@example.com")
        _, manifest = redact_document(doc, _settings(redaction_mode="placeholder"))
        assert manifest.mode == "placeholder"


# ---------------------------------------------------------------------------
# Suppress mode
# ---------------------------------------------------------------------------


class TestSuppressMode:
    def test_all_entities_become_redacted(self):
        doc = _doc("Alice Johnson called from alice@example.com.")
        _, manifest = redact_document(doc, _settings(redaction_mode="suppress"))
        text = doc.pages[0].markdown
        assert "[REDACTED]" in text
        assert "alice@example.com" not in text
        for entity in manifest.entities:
            assert entity.replacement == "[REDACTED]"

    def test_no_type_info_leaked(self):
        doc = _doc("Contact: dave@corp.com, +1-555-123-4567")
        _, manifest = redact_document(doc, _settings(redaction_mode="suppress"))
        text = doc.pages[0].markdown
        assert "[EMAIL_ADDRESS]" not in text
        assert "[PHONE_NUMBER]" not in text


# ---------------------------------------------------------------------------
# Pseudonymize mode
# ---------------------------------------------------------------------------


class TestPseudonymizeMode:
    def test_same_name_gets_same_pseudonym(self):
        doc = _doc(
            "Alice Johnson signed the contract.",
            "Alice Johnson approved the invoice.",
        )
        _, manifest = redact_document(doc, _settings(redaction_mode="pseudonymize"))
        p1 = doc.pages[0].markdown
        p2 = doc.pages[1].markdown
        # Extract the pseudonym used on page 1
        assert "Alice Johnson" not in p1
        assert "Alice Johnson" not in p2
        # Both pages should have the same replacement for Alice Johnson
        replacement = manifest.pseudonym_map.get("alice johnson")
        assert replacement is not None
        assert replacement in p1
        assert replacement in p2

    def test_different_names_get_different_pseudonyms(self):
        doc = _doc("Alice Johnson and Bob Smith attended the meeting.")
        _, manifest = redact_document(doc, _settings(redaction_mode="pseudonymize"))
        assert "Alice Johnson" not in doc.pages[0].markdown
        assert "Bob Smith" not in doc.pages[0].markdown
        alice_pseudo = manifest.pseudonym_map.get("alice johnson")
        bob_pseudo = manifest.pseudonym_map.get("bob smith")
        assert alice_pseudo is not None
        assert bob_pseudo is not None
        assert alice_pseudo != bob_pseudo

    def test_pseudonym_labels_are_human_readable(self):
        doc = _doc("Dr. Carol White reviewed the case.")
        _, manifest = redact_document(doc, _settings(redaction_mode="pseudonymize"))
        # All PERSON pseudonyms should follow "Person X" format
        for orig, pseudo in manifest.pseudonym_map.items():
            if any(
                e.entity_type == "PERSON" and e.original.lower() == orig for e in manifest.entities
            ):
                assert pseudo.startswith("Person ") or pseudo.startswith("Entity ")

    def test_emails_use_placeholder_in_pseudonymize_mode(self):
        # Emails are not pseudonymizable — they always get [EMAIL_ADDRESS]
        doc = _doc("Reach Alice at alice@example.com.")
        _, manifest = redact_document(doc, _settings(redaction_mode="pseudonymize"))
        assert "[EMAIL_ADDRESS]" in doc.pages[0].markdown

    def test_manifest_contains_pseudonym_map(self):
        doc = _doc("Eve Miller submitted the claim.")
        _, manifest = redact_document(doc, _settings(redaction_mode="pseudonymize"))
        assert isinstance(manifest.pseudonym_map, dict)


# ---------------------------------------------------------------------------
# Language isolation — German document should not produce English NER false positives
# ---------------------------------------------------------------------------


class TestLanguageIsolation:
    def test_german_text_no_ner_false_positives(self):
        """German words must not be misclassified as PERSON/LOCATION by English NER."""
        german_text = (
            "Ich kündige hiermit den Versicherungsvertrag zum nächstmöglichen Termin. "
            "Die Kündigung betrifft die Polizzennummer 12345678. "
            "Bitte senden Sie die Bestätigung an meine neue Adresse."
        )
        doc = _doc(german_text, language="de")
        _, manifest = redact_document(
            doc,
            _settings(redaction_entities=["PERSON", "LOCATION", "EMAIL_ADDRESS", "PHONE_NUMBER"]),
        )
        # Words like "Kündigung", "Termin", "Adresse" should NOT appear as redacted entities
        false_positive_words = {
            "kündigung",
            "termin",
            "adresse",
            "polizzennummer",
            "versicherungsvertrag",
            "bestätigung",
        }
        redacted_originals = {e.original.lower() for e in manifest.entities}
        overlap = false_positive_words & redacted_originals
        assert not overlap, f"German words incorrectly redacted as PII: {overlap}"

    def test_german_text_still_catches_email(self):
        """Regex-based types (email, phone, IBAN) must work regardless of language."""
        doc = _doc(
            "Kontakt: max.mustermann@beispiel.de, IBAN: DE89370400440532013000",
            language="de",
        )
        _, manifest = redact_document(
            doc,
            _settings(
                redaction_entities=["EMAIL_ADDRESS", "IBAN_CODE"],
            ),
        )
        types_found = {e.entity_type for e in manifest.entities}
        assert "EMAIL_ADDRESS" in types_found
        assert "max.mustermann@beispiel.de" not in doc.pages[0].markdown

    def test_unsupported_language_runs_regex_only(self):
        """For languages with no spaCy model, NER types are skipped but regex runs."""
        doc = _doc("Kontakta oss på info@foretag.se.", language="sv")  # Swedish
        _, manifest = redact_document(
            doc,
            _settings(redaction_entities=["PERSON", "EMAIL_ADDRESS"]),
        )
        # EMAIL should be caught by regex even for unsupported language
        assert "info@foretag.se" not in doc.pages[0].markdown
        # PERSON entities from NER should not fire (Swedish → no model)
        ner_hits = [e for e in manifest.entities if e.entity_type == "PERSON"]
        assert len(ner_hits) == 0

    def test_redaction_language_override(self):
        """redaction_language setting overrides detected_language for NER model selection."""
        # Document has detected_language="sv" (Swedish, no model), but we override to "en"
        # so the English NER model runs and catches PERSON.
        doc = _doc("Alice Johnson attended the meeting.", language="sv")
        _, manifest = redact_document(
            doc,
            _settings(redaction_entities=["PERSON"], redaction_language="en"),
        )
        assert "Alice Johnson" not in doc.pages[0].markdown
        assert any(e.entity_type == "PERSON" for e in manifest.entities)


# ---------------------------------------------------------------------------
# Multi-page consistency
# ---------------------------------------------------------------------------


class TestMultiPage:
    def test_page_number_recorded_in_manifest(self):
        doc = _doc("alice@example.com", "bob@example.com")
        _, manifest = redact_document(doc, _settings())
        page_nums = {e.page_num for e in manifest.entities}
        assert 1 in page_nums
        assert 2 in page_nums

    def test_all_pages_redacted(self):
        doc = _doc("Page 1: test@a.com", "Page 2: other@b.com", "Page 3: third@c.com")
        _, manifest = redact_document(doc, _settings())
        for page in doc.pages:
            assert "@" not in page.markdown

    def test_pseudonym_consistent_across_pages(self):
        doc = _doc(
            "Alice Johnson is the plaintiff.",
            "The defendant disputes Alice Johnson's claim.",
            "Alice Johnson provided evidence on day 3.",
        )
        _, manifest = redact_document(doc, _settings(redaction_mode="pseudonymize"))
        replacement = manifest.pseudonym_map.get("alice johnson")
        assert replacement is not None
        for page in doc.pages:
            assert "Alice Johnson" not in page.markdown
            assert replacement in page.markdown


# ---------------------------------------------------------------------------
# Manifest completeness
# ---------------------------------------------------------------------------


class TestManifest:
    def test_entity_types_recorded(self):
        doc = _doc("alice@example.com and +1-555-123-4567")
        _, manifest = redact_document(doc, _settings())
        assert "EMAIL_ADDRESS" in manifest.entity_types
        assert "PHONE_NUMBER" in manifest.entity_types

    def test_created_at_is_set(self):
        doc = _doc("test@example.com")
        _, manifest = redact_document(doc, _settings())
        assert manifest.created_at != ""

    def test_empty_doc_produces_empty_manifest(self):
        doc = _doc("No personal information here at all.", language="en")
        _, manifest = redact_document(
            doc,
            _settings(redaction_entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE"]),
        )
        assert manifest.total_redactions == 0
        assert manifest.entities == []
