"""Local candidate buffer populated from the user's visible X For You feed."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from acquisition.content_models import PostCandidate, utc_now_iso
from acquisition.twitter_mcp import CandidateSource


@dataclass
class BufferedCandidate:
    user_id: str
    session_id: str
    post: PostCandidate
    observed_at: str
    sequence: int


class ForYouCandidateSource:
    """Candidate source backed by posts observed by the Chrome extension."""

    def __init__(self, fallback: CandidateSource | None = None, max_per_user: int = 500) -> None:
        self.fallback = fallback
        self.max_per_user = max_per_user
        self._lock = asyncio.Lock()
        self._sequence = 0
        self._candidates: dict[tuple[str, str], BufferedCandidate] = {}

    async def ingest(
        self,
        *,
        user_id: str,
        session_id: str,
        posts: list[PostCandidate],
        observed_at: str | None = None,
    ) -> int:
        if not posts:
            return 0

        async with self._lock:
            accepted = 0
            now = observed_at or utc_now_iso()
            for post in posts:
                self._sequence += 1
                key = (user_id, post.post_id)
                self._candidates[key] = BufferedCandidate(
                    user_id=user_id,
                    session_id=session_id,
                    post=post.model_copy(deep=True),
                    observed_at=now,
                    sequence=self._sequence,
                )
                accepted += 1

            self._trim_locked(user_id)
            return accepted

    async def fetch_candidates(
        self, query_context: dict[str, Any], limit: int
    ) -> list[PostCandidate]:
        user_id = str(query_context.get("user_id") or "")
        session_id = str(query_context.get("session_id") or "")
        prefer_for_you = query_context.get("candidate_source") in {None, "x_for_you", "for_you"}
        for_you_only = _for_you_only(query_context)
        target_count = _positive_int(query_context.get("target_count")) or limit
        recent_window_s = _positive_float(query_context.get("recent_activity_window_s"))
        if recent_window_s is None:
            recent_window_s = _positive_float(query_context.get("recent_window_s"))

        candidates: list[PostCandidate] = []
        seen: set[str] = set()

        if prefer_for_you and user_id:
            candidates = await self._list_buffered(
                user_id=user_id,
                session_id=session_id,
                limit=limit,
                recent_window_s=recent_window_s,
            )
            seen.update(candidate.post_id for candidate in candidates)
            if len(candidates) >= min(limit, target_count):
                return candidates[:limit]

        if for_you_only:
            return candidates[:limit]

        if len(candidates) < limit and self.fallback is not None:
            try:
                fallback = await self.fallback.fetch_candidates(query_context, limit - len(candidates))
            except Exception:
                if candidates:
                    return candidates[:limit]
                raise
            for candidate in fallback:
                if candidate.post_id in seen:
                    continue
                candidates.append(candidate)
                seen.add(candidate.post_id)
                if len(candidates) >= limit:
                    break

        return candidates[:limit]

    async def count(self, user_id: str, session_id: str | None = None) -> int:
        async with self._lock:
            return sum(
                1
                for candidate in self._candidates.values()
                if candidate.user_id == user_id
                and (session_id is None or candidate.session_id == session_id)
            )

    async def _list_buffered(
        self,
        *,
        user_id: str,
        session_id: str,
        limit: int,
        recent_window_s: float | None = None,
    ) -> list[PostCandidate]:
        async with self._lock:
            now = datetime.now(timezone.utc)
            candidates = [
                candidate
                for candidate in self._candidates.values()
                if candidate.user_id == user_id
                and (not session_id or candidate.session_id == session_id)
                and _is_recent(candidate.observed_at, now, recent_window_s)
            ]
            candidates.sort(key=lambda candidate: candidate.sequence, reverse=True)
            posts: list[PostCandidate] = []
            for candidate in candidates[:limit]:
                post = candidate.post.model_copy(deep=True)
                post.metadata = dict(post.metadata)
                post.metadata.update(
                    {
                        "observed_at": candidate.observed_at,
                        "for_you_sequence": candidate.sequence,
                    }
                )
                posts.append(post)
            return posts

    def _trim_locked(self, user_id: str) -> None:
        user_candidates = [
            (key, candidate)
            for key, candidate in self._candidates.items()
            if candidate.user_id == user_id
        ]
        if len(user_candidates) <= self.max_per_user:
            return

        user_candidates.sort(key=lambda item: item[1].sequence, reverse=True)
        keep = {key for key, _candidate in user_candidates[: self.max_per_user]}
        for key, _candidate in user_candidates[self.max_per_user :]:
            if key not in keep:
                self._candidates.pop(key, None)


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _for_you_only(query_context: dict[str, Any]) -> bool:
    value = (
        query_context.get("for_you_only")
        or query_context.get("strict_for_you")
        or query_context.get("disable_twitter_fallback")
    )
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value:
        return True

    return (
        query_context.get("candidate_source") in {"x_for_you", "for_you"}
        and _truthy(query_context.get("require_interest_profile"))
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _is_recent(value: str, now: datetime, window_s: float | None) -> bool:
    if window_s is None:
        return True

    observed_at = _parse_iso_datetime(value)
    if observed_at is None:
        return False
    age_s = (now - observed_at).total_seconds()
    return 0 <= age_s <= window_s


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
