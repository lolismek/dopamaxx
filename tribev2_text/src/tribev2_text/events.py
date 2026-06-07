"""Synthetic text event construction."""

from __future__ import annotations

import re
from hashlib import sha256
from typing import Any

DEFAULT_WORDS_PER_MINUTE = 180.0
EVENT_STRATEGY = "synthetic_word_events_v1"
_WORD_RE = re.compile(r"https?://\S+|[#@]?\w+(?:[-'’]\w+)*", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Collapse whitespace and reject empty text."""

    normalized = _SPACE_RE.sub(" ", text).strip()
    if not normalized:
        raise ValueError("text must not be empty")
    return normalized


def tokenize_words(text: str) -> list[str]:
    """Return deterministic word-like tokens for synthetic timing."""

    normalized = normalize_text(text)
    return [match.group(0) for match in _WORD_RE.finditer(normalized)]


def build_synthetic_word_events(
    text: str,
    *,
    words_per_minute: float = DEFAULT_WORDS_PER_MINUTE,
) -> list[dict[str, Any]]:
    """Build TRIBE-compatible word events from raw text."""

    normalized = normalize_text(text)
    tokens = tokenize_words(normalized)
    if not tokens:
        raise ValueError("text must contain at least one word token")
    if words_per_minute <= 0:
        raise ValueError("words_per_minute must be positive")

    seconds_per_word = 60.0 / words_per_minute
    duration = seconds_per_word * 0.8
    timeline = f"text:{source_hash(normalized)[:16]}"
    events: list[dict[str, Any]] = []
    for index, token in enumerate(tokens):
        events.append(
            {
                "type": "Word",
                "text": token,
                "start": round(index * seconds_per_word, 6),
                "duration": round(duration, 6),
                "sequence_id": 0,
                "sentence": normalized,
                "context": normalized,
                "language": "english",
                "timeline": timeline,
                "subject": "default",
            }
        )
    return events


def source_hash(normalized_text: str) -> str:
    """Return the source hash for normalized text."""

    return sha256(normalized_text.encode("utf-8")).hexdigest()


def estimated_duration_seconds(
    word_count: int,
    *,
    words_per_minute: float = DEFAULT_WORDS_PER_MINUTE,
) -> float:
    """Return the deterministic text duration used for synthetic events."""

    if word_count <= 0:
        return 0.0
    if words_per_minute <= 0:
        raise ValueError("words_per_minute must be positive")
    return word_count * 60.0 / words_per_minute

