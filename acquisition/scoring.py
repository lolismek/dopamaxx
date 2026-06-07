"""Embedding and preference scoring for microdose candidates."""

from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from typing import Protocol

import httpx

from acquisition.content_models import PostCandidate, PostReaction

TRIBE_EMBED_URL_ENV = "DOPAMAXX_TRIBE_EMBED_URL"
TRIBE_EMBED_KEY_ENV = "DOPAMAXX_TRIBE_EMBED_KEY"


class EmbeddingProvider(Protocol):
    async def embed_post(self, post: PostCandidate) -> list[float]:
        """Return a vector embedding for a post."""


class HashEmbeddingProvider:
    """Stable local embedding fallback for tests and offline demos."""

    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions

    async def embed_post(self, post: PostCandidate) -> list[float]:
        text = f"{post.author or ''}\n{post.text}\n{post.url or ''}"
        vector = [0.0] * self.dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % self.dimensions
            sign = 1.0 if digest[2] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


class HttpEmbeddingProvider:
    """Thin adapter for a hosted Tribe-like embedding service."""

    def __init__(self, url: str, api_key: str | None = None, timeout_s: float = 10.0) -> None:
        self.url = url
        self.api_key = api_key
        self.timeout_s = timeout_s

    async def embed_post(self, post: PostCandidate) -> list[float]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.post(
                self.url,
                headers=headers,
                json={
                    "post_id": post.post_id,
                    "text": post.text,
                    "author": post.author,
                    "url": post.url,
                    "media_urls": post.media_urls,
                    "metadata": post.metadata,
                },
            )
            response.raise_for_status()
            payload = response.json()

        embedding = payload.get("embedding") or payload.get("vector")
        if not isinstance(embedding, list):
            raise ValueError("embedding response must include an embedding or vector array")
        return [float(value) for value in embedding]


def embedding_provider_from_env() -> EmbeddingProvider:
    url = os.environ.get(TRIBE_EMBED_URL_ENV)
    if not url:
        return HashEmbeddingProvider()
    return HttpEmbeddingProvider(url=url, api_key=os.environ.get(TRIBE_EMBED_KEY_ENV))


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    length = min(len(left), len(right))
    dot = sum(left[index] * right[index] for index in range(length))
    left_norm = math.sqrt(sum(left[index] * left[index] for index in range(length)))
    right_norm = math.sqrt(sum(right[index] * right[index] for index in range(length)))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


@dataclass(frozen=True)
class ScoreResult:
    predicted_reward: float
    rationale: str


class PreferenceScorer:
    def __init__(self, miss_penalty: float = 0.35) -> None:
        self.miss_penalty = miss_penalty

    def score(self, embedding: list[float], reactions: list[PostReaction]) -> ScoreResult:
        hits = [reaction for reaction in reactions if reaction.label == "hit" and reaction.embedding]
        misses = [reaction for reaction in reactions if reaction.label == "miss" and reaction.embedding]

        hit_score = self._weighted_max_similarity(embedding, hits)
        miss_score = self._weighted_mean_similarity(embedding, misses)
        predicted = hit_score - self.miss_penalty * miss_score

        if hits:
            rationale = f"nearest hit similarity {hit_score:.3f}; miss penalty {miss_score:.3f}"
        else:
            rationale = "no hit history yet; ranked with neutral local prior"
        return ScoreResult(predicted_reward=predicted, rationale=rationale)

    @staticmethod
    def _weighted_max_similarity(embedding: list[float], reactions: list[PostReaction]) -> float:
        if not reactions:
            return 0.0
        return max(
            cosine_similarity(embedding, reaction.embedding) * max(reaction.reward_score, 0.05)
            for reaction in reactions
        )

    @staticmethod
    def _weighted_mean_similarity(embedding: list[float], reactions: list[PostReaction]) -> float:
        if not reactions:
            return 0.0

        weights = [max(abs(reaction.reward_score), 0.05) for reaction in reactions]
        weighted = [
            cosine_similarity(embedding, reaction.embedding) * weight
            for reaction, weight in zip(reactions, weights, strict=True)
        ]
        total_weight = sum(weights)
        if total_weight == 0:
            return 0.0
        return sum(weighted) / total_weight

