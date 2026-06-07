from __future__ import annotations

import json
import math

import pytest

from tribev2_text import DeterministicFakeBackend, cosine_similarity, encode_text
from tribev2_text.signature import SCHEMA_VERSION, TextSignature


def test_encode_text_returns_storage_ready_signature() -> None:
    signature = encode_text(
        "This text should produce a deterministic fake activation.",
        backend=DeterministicFakeBackend(),
    )

    assert signature.schema_version == SCHEMA_VERSION
    assert signature.backend == "fake"
    assert signature.model_id == "deterministic-fake-v1"
    assert signature.event_strategy == "synthetic_word_events_v1"
    assert signature.text_stats.word_count == 8
    assert signature.prediction_shape == [4, 64]
    assert len(signature.similarity_vector) == 1536
    assert math.isclose(_norm(signature.similarity_vector), 1.0, rel_tol=1e-12)


def test_encode_text_is_repeatable() -> None:
    backend = DeterministicFakeBackend()
    left = encode_text("same text", backend=backend)
    right = encode_text("same   text", backend=backend)

    assert left.to_dict() == right.to_dict()
    assert cosine_similarity(left, right) == pytest.approx(1.0)


def test_encode_text_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="empty"):
        encode_text("", backend=DeterministicFakeBackend())


def test_signature_round_trips_from_json() -> None:
    signature = encode_text("round trip", backend=DeterministicFakeBackend())
    body = json.loads(signature.to_json())
    assert TextSignature.from_dict(body).to_dict() == signature.to_dict()


def test_cosine_similarity_rejects_mismatched_dimensions() -> None:
    with pytest.raises(ValueError, match="same length"):
        cosine_similarity([1.0, 2.0], [1.0])


def _norm(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values))

