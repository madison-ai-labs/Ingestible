"""Language detection and language-aware tokenization — WP 4.2."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Snowball stemmer language names (subset of NLTK / PyStemmer)
SNOWBALL_LANGUAGES = {
    "ar": "arabic",
    "da": "danish",
    "de": "german",
    "en": "english",
    "es": "spanish",
    "fi": "finnish",
    "fr": "french",
    "hu": "hungarian",
    "it": "italian",
    "nl": "dutch",
    "no": "norwegian",
    "pt": "portuguese",
    "ro": "romanian",
    "ru": "russian",
    "sv": "swedish",
    "tr": "turkish",
}


def detect_language(text: str) -> str:
    """Detect the language of a text. Returns ISO 639-1 code (e.g. 'en').

    Uses langdetect if available, falls back to 'en'.
    """
    if not text or len(text.strip()) < 20:
        return "en"

    try:
        from langdetect import detect

        lang = detect(text[:5000])  # sample first 5000 chars for speed
        return lang
    except ImportError:
        logger.debug("langdetect not installed, defaulting to 'en'")
        return "en"
    except Exception:
        return "en"


def get_tokenizer(lang: str = "en"):
    """Return a tokenization function for the given language.

    Uses Snowball stemmer if available, falls back to simple whitespace tokenizer.
    """
    snowball_lang = SNOWBALL_LANGUAGES.get(lang, None)

    if snowball_lang:
        try:
            from Stemmer import Stemmer

            stemmer = Stemmer(snowball_lang)

            def _tokenize_stemmed(text: str) -> list[str]:
                tokens = _simple_tokenize(text)
                return stemmer.stemWords(tokens)

            return _tokenize_stemmed
        except ImportError:
            pass

    return _simple_tokenize


def _simple_tokenize(text: str) -> list[str]:
    """Simple whitespace + lowercase tokenizer with basic cleanup."""
    return [w for w in re.split(r"\W+", text.lower()) if w]
