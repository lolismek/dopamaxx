"""Text-only TRIBE v2 signature helpers."""

from .backends import DeterministicFakeBackend, TribeV2Backend
from .events import build_synthetic_word_events, normalize_text, tokenize_words
from .signature import (
    SCHEMA_VERSION,
    TextSignature,
    cosine_similarity,
    encode_text,
    load_signature,
)

__all__ = [
    "SCHEMA_VERSION",
    "DeterministicFakeBackend",
    "TextSignature",
    "TribeV2Backend",
    "build_synthetic_word_events",
    "cosine_similarity",
    "encode_text",
    "load_signature",
    "normalize_text",
    "tokenize_words",
]

