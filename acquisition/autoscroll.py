"""Locked In autoscroll orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from acquisition.content_models import (
    AgentRun,
    AutoscrollStartRequest,
    PostCandidate,
    QueueItem,
    utc_now_iso,
)
from acquisition.content_store import ContentStore, finish_fields
from acquisition.scoring import EmbeddingProvider, PreferenceScorer
from acquisition.twitter_mcp import CandidateSource


@dataclass(frozen=True)
class ScoredCandidate:
    post: PostCandidate
    embedding: list[float]
    predicted_reward: float
    rationale: str


class AutoscrollService:
    """Runs live Twitter MCP candidate retrieval for manual/demo microdose feeds."""

    def __init__(
        self,
        *,
        store: ContentStore,
        candidate_source: CandidateSource,
        embedder: EmbeddingProvider,
        scorer: PreferenceScorer | None = None,
    ) -> None:
        self.store = store
        self.candidate_source = candidate_source
        self.embedder = embedder
        self.scorer = scorer or PreferenceScorer()
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

        try:
            while (
                len(scored) < request.target_count
                and asyncio.get_running_loop().time() < deadline
                and not cancel_event.is_set()
            ):
                reactions = await self.store.list_preference_reactions(request.user_id)
                queued = await self.store.list_ready_queue(
                    user_id=request.user_id,
                    session_id=request.session_id,
                    limit=500,
                )
                seen_post_ids = {reaction.post_id for reaction in reactions}
                seen_post_ids.update(item.post_id for item in queued)
                query_context = self._query_context(request, reactions)
                fetch_limit = max(20, (request.target_count - len(scored)) * 3)
                candidates = await self.candidate_source.fetch_candidates(
                    query_context=query_context,
                    limit=fetch_limit,
                )
                fetched_count += len(candidates)

                new_candidates = 0
                for candidate in candidates:
                    if candidate.post_id in seen_post_ids or candidate.post_id in scored:
                        continue
                    embedding = await self.embedder.embed_post(candidate)
                    score = self.scorer.score(embedding, reactions)
                    scored[candidate.post_id] = ScoredCandidate(
                        post=candidate,
                        embedding=embedding,
                        predicted_reward=score.predicted_reward,
                        rationale=score.rationale,
                    )
                    new_candidates += 1

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
                    },
                )

            if cancel_event.is_set():
                await self.store.update_agent_run(
                    run.run_id,
                    finish_fields(
                        "cancelled",
                        fetched_count=fetched_count,
                        accepted_count=min(len(scored), request.target_count),
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
        hits = [reaction for reaction in reactions if getattr(reaction, "label", None) == "hit"]
        misses = [reaction for reaction in reactions if getattr(reaction, "label", None) == "miss"]

        context = dict(request.query_context)
        context.update(
            {
                "agent_mode": "locked_in_manual_live_scroll",
                "user_id": request.user_id,
                "session_id": request.session_id,
                "target_count": request.target_count,
                "positive_examples": [reaction.text[:280] for reaction in hits[:8]],
                "negative_examples": [reaction.text[:280] for reaction in misses[:5]],
            }
        )
        return context

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
