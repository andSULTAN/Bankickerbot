"""Small text helpers used by the scoring engine."""

from __future__ import annotations

import hashlib
import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)


def normalize_text(text: str) -> str:
    """Lowercase, drop punctuation/emoji, collapse whitespace.

    Used both for keyword matching and for the comment-template hash, so that
    "Kirish 👉 t.me/xxx" and "kirish t me xxx!!!" collapse to the same string.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    text = _NON_WORD_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def template_hash(text: str) -> str:
    """Stable hash of the normalized comment text (v1 template detection)."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def find_patterns(text: str, patterns: list[str]) -> list[str]:
    """Return the regex patterns that match `text` (case-insensitive)."""
    if not text:
        return []
    hits: list[str] = []
    for pattern in patterns:
        try:
            if re.search(pattern, text, flags=re.IGNORECASE):
                hits.append(pattern)
        except re.error:  # a broken pattern in YAML must not kill the scan
            continue
    return hits


def find_keywords(text: str, keywords: list[str]) -> list[str]:
    """Return the keywords contained in `text`, compared on normalized text."""
    if not text:
        return []
    haystack = normalize_text(text)
    return [kw for kw in keywords if normalize_text(kw) and normalize_text(kw) in haystack]


def find_emojis(text: str, emojis: list[str]) -> list[str]:
    if not text:
        return []
    return [emoji for emoji in emojis if emoji in text]
