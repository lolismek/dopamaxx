"""Locked In autoscroll orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

from acquisition.content_models import (
    AgentRun,
    AutoscrollStartRequest,
    PostCandidate,
    QueueItem,
    utc_now_iso,
)
from acquisition.content_store import ContentStore, finish_fields
from acquisition.scoring import EmbeddingProvider
from acquisition.twitter_mcp import CandidateSource

DEFAULT_RECENT_ACTIVITY_WINDOW_S = 120.0
INTEREST_DWELL_MS = 3000
MAX_INTEREST_KEYWORDS = 12
MIN_TOPIC_MATCHES = 2
RELAXED_FILL_SCORE_MULTIPLIER = 0.6
RELAXED_FILL_MAX_SCORE = 0.45
ANCHOR_ALLOWLIST = {"ai", "ml", "llm", "gpt4", "gpt5", "box", "cli"}
STOPWORDS = {
    "about",
    "after",
    "again",
    "all",
    "also",
    "and",
    "another",
    "any",
    "are",
    "around",
    "back",
    "because",
    "before",
    "being",
    "been",
    "best",
    "but",
    "can",
    "could",
    "everyone",
    "for",
    "following",
    "from",
    "get",
    "got",
    "great",
    "has",
    "have",
    "how",
    "into",
    "just",
    "like",
    "more",
    "most",
    "new",
    "not",
    "now",
    "old",
    "one",
    "our",
    "out",
    "please",
    "price",
    "over",
    "post",
    "posts",
    "real",
    "see",
    "season",
    "still",
    "story",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "they",
    "this",
    "thread",
    "through",
    "time",
    "tweet",
    "two",
    "use",
    "used",
    "using",
    "via",
    "version",
    "was",
    "were",
    "what",
    "when",
    "where",
    "who",
    "why",
    "will",
    "with",
    "would",
    "year",
    "years",
    "you",
    "your",
    "full",
    "game",
    "games",
    "team",
    "teams",
    "while",
}


@dataclass(frozen=True)
class ScoredCandidate:
    post: PostCandidate
    predicted_reward: float
    rationale: str


@dataclass(frozen=True)
class InterestProfile:
    keywords: tuple[str, ...]
    anchors: tuple[str, ...]
    examples: tuple[str, ...]
    dwell_ms: tuple[int, ...]


class AutoscrollService:
    """Runs live Twitter MCP candidate retrieval for manual/demo microdose feeds."""

    def __init__(
        self,
        *,
        store: ContentStore,
        candidate_source: CandidateSource,
        embedder: EmbeddingProvider,
        scorer: Any | None = None,
    ) -> None:
        self.store = store
        self.candidate_source = candidate_source
        self.embedder = embedder
        self.scorer = scorer
        self._active_by_session: dict[tuple[str, str], str] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def start(self, request: AutoscrollStartRequest) -> AgentRun:
        key = (request.user_id, request.session_id)
        active_run_id = self._active_by_session.get(key)
        active_task = self._tasks.get(active_run_id or "")
        if active_run_id and active_task and not active_task.done():
            raise ValueError(f"autoscroll run already active for session {request.session_id}")

        run = AgentRun(
            user_id=request.user_id,
            session_id=request.session_id,
            target_count=request.target_count,
        )
        await self.store.create_agent_run(run)

        cancel_event = asyncio.Event()
        task = asyncio.create_task(self._run(request, run, cancel_event))
        self._active_by_session[key] = run.run_id
        self._cancel_events[run.run_id] = cancel_event
        self._tasks[run.run_id] = task
        task.add_done_callback(lambda _task: self._cleanup(run.run_id, key))
        return run

    async def cancel(self, run_id: str) -> AgentRun | None:
        run = await self.store.get_agent_run(run_id)
        if run is None:
            return None
        if run.status != "running":
            return run

        event = self._cancel_events.get(run_id)
        if event is not None:
            event.set()
        return await self.store.update_agent_run(run_id, finish_fields("cancelled"))

    async def _run(
        self,
        request: AutoscrollStartRequest,
        run: AgentRun,
        cancel_event: asyncio.Event,
    ) -> None:
        fetched_count = 0
        scored: dict[str, ScoredCandidate] = {}
        deadline = asyncio.get_running_loop().time() + request.timeout_s
        empty_fetches = 0
        requires_interest_profile = _requires_interest_profile(request.query_context)

        try:
            while (
                len(scored) < request.target_count
                and asyncio.get_running_loop().time() < deadline
                and not cancel_event.is_set()
            ):
                reactions = await self.store.list_preference_reactions(request.user_id)
                interest_profile = self._interest_profile(reactions)
                queued = await self.store.list_ready_queue(
                    user_id=request.user_id,
                    session_id=request.session_id,
                    limit=500,
                )
                seen_post_ids = {item.post_id for item in queued}
                new_candidates = 0
                if _include_recent_activity_candidates(request.query_context):
                    recent_window_s = _recent_activity_window_s(request.query_context)
                    for candidate in self._recent_reaction_candidates(
                        reactions=reactions,
                        recent_window_s=recent_window_s,
                    ):
                        if candidate.post_id in seen_post_ids or candidate.post_id in scored:
                            continue
                        scored[candidate.post_id] = ScoredCandidate(
                            post=candidate,
                            predicted_reward=self._timer_score(candidate, reactions, interest_profile),
                            rationale=self._timer_rationale(candidate, reactions, interest_profile),
                        )
                        new_candidates += 1
                        if len(scored) >= request.target_count:
                            break

                    if len(scored) >= request.target_count:
                        await self.store.update_agent_run(
                            run.run_id,
                            {
                                "fetched_count": fetched_count,
                                "accepted_count": min(len(scored), request.target_count),
                                "error": None,
                            },
                        )
                        break

                if requires_interest_profile and not interest_profile.keywords:
                    await self.store.update_agent_run(
                        run.run_id,
                        {
                            "fetched_count": fetched_count,
                            "accepted_count": min(len(scored), request.target_count),
                            "error": self._waiting_error(
                                interest_profile,
                                requires_interest_profile=requires_interest_profile,
                            ),
                        },
                    )
                    await asyncio.sleep(0.5)
                    continue

                query_context = self._query_context(request, reactions)
                fetch_limit = max(20, (request.target_count - len(scored)) * 3)
                candidates = await self.candidate_source.fetch_candidates(
                    query_context=query_context,
                    limit=fetch_limit,
                )
                fetched_count += len(candidates)
                relaxed_fill_candidates: list[PostCandidate] = []

                for candidate in candidates:
                    if candidate.post_id in seen_post_ids or candidate.post_id in scored:
                        continue
                    if interest_profile.keywords and not self._matches_interest_profile(
                        candidate,
                        interest_profile,
                    ):
                        relaxed_fill_candidates.append(candidate)
                        continue
                    scored[candidate.post_id] = ScoredCandidate(
                        post=candidate,
                        predicted_reward=self._timer_score(candidate, reactions, interest_profile),
                        rationale=self._timer_rationale(candidate, reactions, interest_profile),
                    )
                    new_candidates += 1
                    if len(scored) >= request.target_count:
                        break

                if (
                    len(scored) < request.target_count
                    and relaxed_fill_candidates
                    and _allow_relaxed_candidate_fill(request.query_context)
                ):
                    for candidate in relaxed_fill_candidates:
                        if candidate.post_id in scored:
                            continue
                        scored[candidate.post_id] = ScoredCandidate(
                            post=candidate,
                            predicted_reward=_relaxed_fill_score(
                                self._timer_score(candidate, reactions, interest_profile)
                            ),
                            rationale=_relaxed_fill_rationale(
                                self._timer_rationale(candidate, reactions, interest_profile)
                            ),
                        )
                        new_candidates += 1
                        if len(scored) >= request.target_count:
                            break

                if new_candidates == 0:
                    empty_fetches += 1
                    if empty_fetches >= 3:
                        break
                    await asyncio.sleep(0.5)
                else:
                    empty_fetches = 0

                await self.store.update_agent_run(
                    run.run_id,
                    {
                        "fetched_count": fetched_count,
                        "accepted_count": min(len(scored), request.target_count),
                        "error": None
                        if scored
                        else self._waiting_error(
                            interest_profile,
                            requires_interest_profile=requires_interest_profile,
                        ),
                    },
                )

            if cancel_event.is_set():
                await self.store.update_agent_run(
                    run.run_id,
                    finish_fields(
                        "cancelled",
                        fetched_count=fetched_count,
                        accepted_count=min(len(scored), request.target_count),
                        error=f"cancelled after queueing {min(len(scored), request.target_count)} timer-selected candidates",
                    ),
                )
                return

            queue_items = self._queue_items(
                run=run,
                scored=sorted(
                    scored.values(),
                    key=lambda candidate: candidate.predicted_reward,
                    reverse=True,
                )[: request.target_count],
            )
            await self.store.insert_queue_items(queue_items)
            await self.store.update_agent_run(
                run.run_id,
                finish_fields(
                    "completed",
                    fetched_count=fetched_count,
                    accepted_count=len(queue_items),
                    queued_count=len(queue_items),
                    error=None
                    if queue_items
                    else self._expired_error(
                        interest_profile,
                        requires_interest_profile=requires_interest_profile,
                    ),
                ),
            )
        except Exception as exc:
            await self.store.update_agent_run(
                run.run_id,
                finish_fields(
                    "failed",
                    fetched_count=fetched_count,
                    accepted_count=min(len(scored), request.target_count),
                    error=str(exc),
                ),
            )

    @staticmethod
    def _query_context(request: AutoscrollStartRequest, reactions: list[Any]) -> dict[str, Any]:
        interest_profile = AutoscrollService._interest_profile(reactions)

        context = dict(request.query_context)
        context.update(
            {
                "agent_mode": "locked_in_manual_live_scroll",
                "user_id": request.user_id,
                "session_id": request.session_id,
                "target_count": request.target_count,
                "selection_signal": "locked_out_long_dwell_type",
                "recent_activity_window_s": _recent_activity_window_s(request.query_context),
                "interest_dwell_ms": INTEREST_DWELL_MS,
                "interest_keywords": list(interest_profile.keywords),
                "positive_examples": list(interest_profile.examples),
                "negative_examples": [],
                "top_dwell_ms": list(interest_profile.dwell_ms),
            }
        )
        return context

    @staticmethod
    def _recent_reaction_candidates(
        *, reactions: list[Any], recent_window_s: float | None
    ) -> list[PostCandidate]:
        if recent_window_s is None:
            return []

        now = datetime.now(timezone.utc)
        recent = [
            reaction
            for reaction in reactions
            if (getattr(reaction, "dwell_ms", 0) or 0) >= INTEREST_DWELL_MS
            and _is_recent_iso(getattr(reaction, "created_at", None), now, recent_window_s)
        ]
        recent.sort(
            key=lambda reaction: (
                _parse_iso_datetime(getattr(reaction, "created_at", None)) or datetime.min.replace(tzinfo=timezone.utc),
                getattr(reaction, "dwell_ms", 0) or 0,
            ),
            reverse=True,
        )

        candidates: list[PostCandidate] = []
        for reaction in recent:
            candidates.append(
                PostCandidate(
                    post_id=str(getattr(reaction, "post_id", "")),
                    text=str(getattr(reaction, "text", "") or ""),
                    author=getattr(reaction, "author", None),
                    url=getattr(reaction, "url", None),
                    media_urls=list(getattr(reaction, "media_urls", []) or []),
                    source="locked_out_recent_activity",
                    metadata={
                        "reaction_id": getattr(reaction, "reaction_id", None),
                        "dwell_ms": getattr(reaction, "dwell_ms", 0) or 0,
                        "observed_at": getattr(reaction, "created_at", None),
                        "activity_window_s": recent_window_s,
                        "source": getattr(reaction, "metadata", {}).get("source")
                        if isinstance(getattr(reaction, "metadata", {}), dict)
                        else None,
                    },
                )
            )
        return candidates

    @staticmethod
    def _timer_score(
        candidate: PostCandidate,
        reactions: list[Any],
        interest_profile: InterestProfile | None = None,
    ) -> float:
        candidate_dwell_ms = _metadata_number(candidate.metadata, "dwell_ms")
        if candidate_dwell_ms is None:
            candidate_dwell_ms = _metadata_number(candidate.metadata, "timer_dwell_ms")
        if candidate_dwell_ms is not None:
            base_score = _normalize_dwell_score(candidate_dwell_ms)
            return _interest_boosted_score(base_score, candidate, interest_profile)

        dwell_values = [
            float(getattr(reaction, "dwell_ms", 0) or 0)
            for reaction in reactions
            if (getattr(reaction, "dwell_ms", 0) or 0) >= INTEREST_DWELL_MS
        ]
        if not dwell_values:
            return 0.5
        return _interest_boosted_score(
            _normalize_dwell_score(max(dwell_values)),
            candidate,
            interest_profile,
        )

    @staticmethod
    def _timer_rationale(
        candidate: PostCandidate,
        reactions: list[Any],
        interest_profile: InterestProfile | None = None,
    ) -> str:
        candidate_dwell_ms = _metadata_number(candidate.metadata, "dwell_ms")
        if candidate_dwell_ms is None:
            candidate_dwell_ms = _metadata_number(candidate.metadata, "timer_dwell_ms")
        topic_matches = _topic_matches(candidate, interest_profile)
        if candidate_dwell_ms is not None:
            return _with_topic_rationale(
                f"long-dwell type selection; candidate dwell {int(candidate_dwell_ms)}ms",
                topic_matches,
            )

        dwell_values = [
            int(getattr(reaction, "dwell_ms", 0) or 0)
            for reaction in reactions
            if (getattr(reaction, "dwell_ms", 0) or 0) >= INTEREST_DWELL_MS
        ]
        if not dwell_values:
            return "long-dwell type selection; no engaged-post signal yet"
        return _with_topic_rationale(
            f"long-dwell type selection; top locked-out dwell {max(dwell_values)}ms",
            topic_matches,
        )

    @staticmethod
    def _interest_profile(reactions: list[Any]) -> InterestProfile:
        long_dwell = [
            reaction
            for reaction in reactions
            if (getattr(reaction, "dwell_ms", 0) or 0) >= INTEREST_DWELL_MS
        ]
        long_dwell.sort(
            key=lambda reaction: (
                getattr(reaction, "dwell_ms", 0) or 0,
                _parse_iso_datetime(getattr(reaction, "created_at", None))
                or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        token_counts: dict[str, int] = {}
        for reaction in long_dwell[:20]:
            for token in _topic_tokens(getattr(reaction, "text", "") or ""):
                token_counts[token] = token_counts.get(token, 0) + 1

        keywords = tuple(
            token
            for token, _count in sorted(
                token_counts.items(),
                key=lambda item: (item[1], _is_anchor_token(item[0]), len(item[0]), item[0]),
                reverse=True,
            )[:MAX_INTEREST_KEYWORDS]
        )
        anchors = tuple(token for token in keywords if _is_anchor_token(token))
        examples = tuple(
            str(getattr(reaction, "text", "") or "")[:280]
            for reaction in long_dwell[:8]
            if getattr(reaction, "text", "")
        )
        dwell_ms = tuple(int(getattr(reaction, "dwell_ms", 0) or 0) for reaction in long_dwell[:8])
        return InterestProfile(keywords=keywords, anchors=anchors, examples=examples, dwell_ms=dwell_ms)

    @staticmethod
    def _matches_interest_profile(candidate: PostCandidate, interest_profile: InterestProfile) -> bool:
        if not interest_profile.keywords:
            return True
        matches = _topic_matches(candidate, interest_profile)
        required_matches = min(MIN_TOPIC_MATCHES, len(interest_profile.keywords))
        if len(matches) < required_matches:
            return False
        if interest_profile.anchors and not any(match in interest_profile.anchors for match in matches):
            return False
        return True

    @staticmethod
    def _waiting_error(
        interest_profile: InterestProfile,
        *,
        requires_interest_profile: bool = False,
    ) -> str:
        if not interest_profile.keywords:
            if requires_interest_profile:
                return "waiting for an engaged-post signal"
            return "waiting for an engaged-post signal or timer-selected X/For You candidates"
        return f"waiting for candidates matching engaged-post type: {', '.join(interest_profile.keywords[:5])}"

    @staticmethod
    def _expired_error(
        interest_profile: InterestProfile,
        *,
        requires_interest_profile: bool = False,
    ) -> str:
        if not interest_profile.keywords:
            if requires_interest_profile:
                return "no engaged-post signal was available before the run expired"
            return "no engaged-post signal or timer-selected X/For You candidates were available before the run expired"
        return f"no candidates matched engaged-post type: {', '.join(interest_profile.keywords[:5])}"

    @staticmethod
    def _queue_items(run: AgentRun, scored: list[ScoredCandidate]) -> list[QueueItem]:
        created_at = utc_now_iso()
        return [
            QueueItem(
                run_id=run.run_id,
                user_id=run.user_id,
                session_id=run.session_id,
                post_id=candidate.post.post_id,
                text=candidate.post.text,
                author=candidate.post.author,
                url=candidate.post.url,
                media_urls=candidate.post.media_urls,
                predicted_reward=candidate.predicted_reward,
                rank=index,
                rationale=candidate.rationale,
                metadata={
                    "source": candidate.post.source,
                    "candidate_metadata": candidate.post.metadata,
                },
                created_at=created_at,
            )
            for index, candidate in enumerate(scored, start=1)
        ]

    def _cleanup(self, run_id: str, key: tuple[str, str]) -> None:
        self._tasks.pop(run_id, None)
        self._cancel_events.pop(run_id, None)
        if self._active_by_session.get(key) == run_id:
            self._active_by_session.pop(key, None)


def _metadata_number(metadata: dict[str, Any], key: str) -> float | None:
    value = metadata.get(key)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _normalize_dwell_score(dwell_ms: float) -> float:
    return max(0.05, min(1.0, float(dwell_ms) / 3000.0))


def _interest_boosted_score(
    base_score: float,
    candidate: PostCandidate,
    interest_profile: InterestProfile | None,
) -> float:
    matches = _topic_matches(candidate, interest_profile)
    if not matches:
        return base_score
    return min(1.0, base_score + min(0.2, len(matches) * 0.05))


def _relaxed_fill_score(base_score: float) -> float:
    return max(0.05, min(RELAXED_FILL_MAX_SCORE, base_score * RELAXED_FILL_SCORE_MULTIPLIER))


def _relaxed_fill_rationale(base_rationale: str) -> str:
    return f"{base_rationale}; relaxed fill after strict matches"


def _with_topic_rationale(base: str, topic_matches: list[str]) -> str:
    if not topic_matches:
        return base
    return f"{base}; type match {', '.join(topic_matches[:5])}"


def _topic_matches(
    candidate: PostCandidate,
    interest_profile: InterestProfile | None,
) -> list[str]:
    if interest_profile is None or not interest_profile.keywords:
        return []
    tokens = set(_topic_tokens(_candidate_topic_text(candidate)))
    return [keyword for keyword in interest_profile.keywords if keyword in tokens]


def _candidate_topic_text(candidate: PostCandidate) -> str:
    metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
    metadata_text = " ".join(
        str(value)
        for key, value in metadata.items()
        if key in {"title", "description", "topic", "category"}
        and value is not None
    )
    return "\n".join(
        part
        for part in [
            candidate.text,
            metadata_text,
        ]
        if part
    )


def _topic_tokens(text: str) -> list[str]:
    cleaned = re.sub(r"https?://\S+", " ", text.lower())
    cleaned = re.sub(r"@\w+", " ", cleaned)
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9][a-z0-9_+#.-]*", cleaned):
        normalized = _normalize_topic_token(token)
        if normalized is None:
            continue
        if len(normalized) < 3 and normalized not in {"ai", "ml"}:
            continue
        if normalized in STOPWORDS:
            continue
        tokens.append(normalized)
    return tokens


def _normalize_topic_token(token: str) -> str | None:
    normalized = token.strip("._-+#")
    if not normalized:
        return None
    if normalized.isdigit():
        return None
    if any(char.isdigit() for char in normalized) and normalized not in {"gpt4", "gpt5"}:
        return None
    if len(normalized) > 5 and normalized.endswith("ies"):
        normalized = f"{normalized[:-3]}y"
    elif len(normalized) > 4 and normalized.endswith("s") and not normalized.endswith(("ss", "us")):
        normalized = normalized[:-1]
    return normalized


def _is_anchor_token(token: str) -> bool:
    if token in ANCHOR_ALLOWLIST:
        return True
    if token in STOPWORDS:
        return False
    return len(token) >= 5


def _requires_interest_profile(query_context: dict[str, Any]) -> bool:
    value = (
        query_context.get("require_interest_profile")
        or query_context.get("require_7s_interest_profile")
        or query_context.get("strict_long_dwell_profile")
    )
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _include_recent_activity_candidates(query_context: dict[str, Any]) -> bool:
    value = query_context.get("include_recent_activity_candidates")
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    if value is None:
        return False
    return bool(value)


def _allow_relaxed_candidate_fill(query_context: dict[str, Any]) -> bool:
    value = query_context.get("allow_relaxed_candidate_fill")
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    if value is None:
        return True
    return bool(value)


def _recent_activity_window_s(query_context: dict[str, Any]) -> float | None:
    value = DEFAULT_RECENT_ACTIVITY_WINDOW_S
    for key in ("recent_activity_window_s", "activity_window_s", "recent_window_s"):
        if key in query_context:
            value = query_context.get(key)
            break
    try:
        window_s = float(value)
    except (TypeError, ValueError):
        return DEFAULT_RECENT_ACTIVITY_WINDOW_S
    return window_s if window_s > 0 else None


def _is_recent_iso(value: Any, now: datetime, window_s: float) -> bool:
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
