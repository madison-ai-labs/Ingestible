from __future__ import annotations

import tiktoken

_enc: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    global _enc
    if _enc is None:
        _enc = tiktoken.encoding_for_model("gpt-4o-mini")
    return _enc


def count_tokens(text: str) -> int:
    return len(_get_encoder().encode(text))
