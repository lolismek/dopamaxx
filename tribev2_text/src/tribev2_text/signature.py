"""Build and compare text activation signatures."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from hashlib import blake2b
from pathlib import Path
from typing import Any, Mapping, Sequence

from .backends import TextPredictionBackend
from .events import (
    DEFAULT_WORDS_PER_MINUTE,
    EVENT_STRATEGY,
    build_synthetic_word_events,
    estimated_duration_seconds,
    normalize_text,
    source_hash,
    tokenize_words,
)

SCHEMA_VERSION = "tribev2_text.signature.v1"
VECTOR_DIMENSIONS = 1536


@dataclass(frozen=True)
class TextStats:
    char_count: int
    word_count: int
    estimated_duration_s: float


@dataclass(frozen=True)
class ActivationSummary:
    mean: float
    std: float
    min: float
    max: float
    l2_norm: float


@dataclass(frozen=True)
class TextSignature:
    schema_version: str
    source_hash: str
    backend: str
    model_id: str
    event_strategy: str
    text_stats: TextStats
    prediction_shape: list[int]
    activation_summary: ActivationSummary
    similarity_vector: list[float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TextSignature":
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported signature schema: {data.get('schema_version')}")
        return cls(
            schema_version=str(data["schema_version"]),
            source_hash=str(data["source_hash"]),
            backend=str(data["backend"]),
            model_id=str(data["model_id"]),
            event_strategy=str(data["event_strategy"]),
            text_stats=TextStats(**data["text_stats"]),
            prediction_shape=[int(item) for item in data["prediction_shape"]],
            activation_summary=ActivationSummary(**data["activation_summary"]),
            similarity_vector=[float(item) for item in data["similarity_vector"]],
        )


def encode_text(
    text: str,
    *,
    backend: TextPredictionBackend | None = None,
    model_id: str = "facebook/tribev2",
    cache_folder: str | Path = "tribev2_text/.cache",
    device: str = "auto",
    words_per_minute: float = DEFAULT_WORDS_PER_MINUTE,
) -> TextSignature:
    """Encode raw text into a comparable activation signature."""

    if backend is None:
        from .backends import TribeV2Backend

        backend = TribeV2Backend(
            model_id=model_id,
            cache_folder=cache_folder,
            device=device,
        )

    normalized = normalize_text(text)
    tokens = tokenize_words(normalized)
    events = build_synthetic_word_events(
        normalized,
        words_per_minute=words_per_minute,
    )
    prediction = backend.predict(normalized, events)
    stats = _prediction_stats(prediction.predictions)
    vector = _similarity_vector(stats.column_means)
    text_stats = TextStats(
        char_count=len(normalized),
        word_count=len(tokens),
        estimated_duration_s=round(
            estimated_duration_seconds(
                len(tokens),
                words_per_minute=words_per_minute,
            ),
            6,
        ),
    )
    return TextSignature(
        schema_version=SCHEMA_VERSION,
        source_hash=source_hash(normalized),
        backend=prediction.backend,
        model_id=prediction.model_id,
        event_strategy=EVENT_STRATEGY,
        text_stats=text_stats,
        prediction_shape=stats.shape,
        activation_summary=stats.summary,
        similarity_vector=vector,
    )


def load_signature(path: str | Path) -> TextSignature:
    """Load a signature JSON artifact."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return TextSignature.from_dict(data)


def cosine_similarity(
    left: TextSignature | Sequence[float],
    right: TextSignature | Sequence[float],
) -> float:
    """Return cosine similarity between signatures or raw vectors."""

    left_vector = left.similarity_vector if isinstance(left, TextSignature) else left
    right_vector = right.similarity_vector if isinstance(right, TextSignature) else right
    if len(left_vector) != len(right_vector):
        raise ValueError("vectors must have the same length")

    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left_vector, right_vector):
        dot += float(a) * float(b)
        left_norm += float(a) * float(a)
        right_norm += float(b) * float(b)
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / math.sqrt(left_norm * right_norm)


@dataclass(frozen=True)
class _PredictionStats:
    shape: list[int]
    summary: ActivationSummary
    column_means: list[float]


def _prediction_stats(predictions: Any) -> _PredictionStats:
    rows = _rows(predictions)
    row_count = 0
    column_sums: list[float] = []
    total = 0.0
    total_sq = 0.0
    value_count = 0
    min_value = math.inf
    max_value = -math.inf

    for row in rows:
        values = [float(value) for value in row]
        if not values:
            continue
        if not column_sums:
            column_sums = [0.0] * len(values)
        if len(values) != len(column_sums):
            raise ValueError("all prediction rows must have the same width")
        row_count += 1
        for index, value in enumerate(values):
            column_sums[index] += value
            total += value
            total_sq += value * value
            value_count += 1
            min_value = min(min_value, value)
            max_value = max(max_value, value)

    if row_count == 0 or not column_sums:
        raise ValueError("predictions must contain at least one non-empty row")

    mean = total / value_count
    variance = max(0.0, total_sq / value_count - mean * mean)
    column_means = [value / row_count for value in column_sums]
    return _PredictionStats(
        shape=[row_count, len(column_sums)],
        summary=ActivationSummary(
            mean=mean,
            std=math.sqrt(variance),
            min=min_value,
            max=max_value,
            l2_norm=math.sqrt(total_sq),
        ),
        column_means=column_means,
    )


def _rows(predictions: Any) -> Any:
    if hasattr(predictions, "tolist"):
        return predictions.tolist()
    return predictions


def _similarity_vector(column_means: Sequence[float]) -> list[float]:
    centered = _zscore(column_means)
    buckets = [0.0] * VECTOR_DIMENSIONS
    for index, value in enumerate(centered):
        digest = blake2b(str(index).encode("ascii"), digest_size=8).digest()
        raw = int.from_bytes(digest, "big")
        bucket = raw % VECTOR_DIMENSIONS
        sign = -1.0 if raw & 1 else 1.0
        buckets[bucket] += sign * value
    return _l2_normalize(buckets)


def _zscore(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    std = math.sqrt(max(0.0, variance))
    if std == 0.0:
        return [0.0 for _value in values]
    return [(value - mean) / std for value in values]


def _l2_normalize(values: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0.0:
        return [0.0 for _value in values]
    return [value / norm for value in values]
