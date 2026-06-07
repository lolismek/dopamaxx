from __future__ import annotations

import pytest

from tribev2_text.events import build_synthetic_word_events, normalize_text, tokenize_words


def test_normalize_text_collapses_whitespace() -> None:
    assert normalize_text("  hello\n\nworld\t ") == "hello world"


def test_normalize_text_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        normalize_text(" \n\t ")


def test_tokenize_words_handles_post_tokens() -> None:
    assert tokenize_words("Hi @alex, see https://example.com #AI") == [
        "Hi",
        "@alex",
        "see",
        "https://example.com",
        "#AI",
    ]


def test_synthetic_word_events_are_deterministic() -> None:
    events = build_synthetic_word_events("hello world", words_per_minute=120)
    assert events == build_synthetic_word_events("hello world", words_per_minute=120)
    assert events[0]["type"] == "Word"
    assert events[0]["start"] == 0.0
    assert events[0]["duration"] == 0.4
    assert events[1]["start"] == 0.5
    assert events[0]["timeline"].startswith("text:")
    assert events[0]["subject"] == "default"

