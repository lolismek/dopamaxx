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


class OpenAIEmbeddingProvider:
    """Embedding provider compatible with the locked-out Supabase capture path."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        timeout_s: float = 10.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    async def embed_post(self, post: PostCandidate) -> list[float]:
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "input": post_embedding_input(post),
                },
            )
            response.raise_for_status()
            payload = response.json()

        embedding = payload.get("data", [{}])[0].get("embedding")
        if not isinstance(embedding, list):
            raise ValueError("OpenAI embedding response must include data[0].embedding")
        return [float(value) for value in embedding]


def embedding_provider_from_env() -> EmbeddingProvider:
    url = os.environ.get(TRIBE_EMBED_URL_ENV)
    if not url:
        openai_api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DOPAMAXX_OPENAI_API_KEY")
        if openai_api_key:
            return OpenAIEmbeddingProvider(
                api_key=openai_api_key,
                model=os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            )
        return HashEmbeddingProvider()
    return HttpEmbeddingProvider(url=url, api_key=os.environ.get(TRIBE_EMBED_KEY_ENV))


def post_embedding_input(post: PostCandidate) -> str:
    return "\n".join(
        part
        for part in [
            f"Author: {post.author}" if post.author else "",
            f"Post: {post.text}" if post.text else "",
            f"Media: {' '.join(post.media_urls)}" if post.media_urls else "",
            f"URL: {post.url}" if post.url else "",
        ]
        if part
    )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) != len(right):
        return 0.0
    length = len(left)
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
    recommended: bool
    nearest_hit_similarity: float
    hit_count: int


class PreferenceScorer:
    def __init__(
        self,
        miss_penalty: float = 0.35,
        min_hit_reward_score: float = 0.35,
        min_hit_similarity: float = 0.35,
        min_predicted_reward: float = 0.05,
    ) -> None:
        self.miss_penalty = miss_penalty
        self.min_hit_reward_score = min_hit_reward_score
        self.min_hit_similarity = min_hit_similarity
        self.min_predicted_reward = min_predicted_reward

    def score(self, embedding: list[float], reactions: list[PostReaction]) -> ScoreResult:
        hits = [
            reaction
            for reaction in reactions
            if reaction.label == "hit"
            and reaction.reward_score >= self.min_hit_reward_score
            and reaction.embedding
        ]
        misses = [reaction for reaction in reactions if reaction.label == "miss" and reaction.embedding]

        hit_score = self._weighted_max_similarity(embedding, hits)
        miss_score = self._weighted_mean_similarity(embedding, misses)
        predicted = hit_score - self.miss_penalty * miss_score
        nearest_hit_similarity = self._max_similarity(embedding, hits)
        recommended = bool(
            hits
            and nearest_hit_similarity >= self.min_hit_similarity
            and predicted >= self.min_predicted_reward
        )

        if hits:
            rationale = (
                f"nearest high-reward locked-out similarity {nearest_hit_similarity:.3f}; "
                f"weighted hit {hit_score:.3f}; miss penalty {miss_score:.3f}"
            )
        else:
            rationale = "no high-reward locked-out embeddings yet"
        return ScoreResult(
            predicted_reward=predicted,
            rationale=rationale,
            recommended=recommended,
            nearest_hit_similarity=nearest_hit_similarity,
            hit_count=len(hits),
        )

    @staticmethod
    def _max_similarity(embedding: list[float], reactions: list[PostReaction]) -> float:
        if not reactions:
            return 0.0
        return max(cosine_similarity(embedding, reaction.embedding) for reaction in reactions)

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
