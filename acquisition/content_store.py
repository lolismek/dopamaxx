"""Persistence for preference reactions, agent runs, and queued feed items."""

from __future__ import annotations

import asyncio
import os
from copy import deepcopy
from typing import Any, Protocol

import httpx

from acquisition.content_models import AgentRun, PostReaction, QueueItem, QueueStatus, utc_now_iso

SUPABASE_URL_ENV = "DOPAMAXX_SUPABASE_URL"
SUPABASE_SERVICE_KEY_ENV = "DOPAMAXX_SUPABASE_SERVICE_ROLE_KEY"
SUPABASE_ANON_KEY_ENV = "DOPAMAXX_SUPABASE_ANON_KEY"


class ContentStore(Protocol):
    async def insert_reaction(self, reaction: PostReaction) -> PostReaction:
        """Persist a dwell-gated Locked Out reaction."""

    async def list_preference_reactions(self, user_id: str, limit: int = 500) -> list[PostReaction]:
        """Return recent hit/miss reactions for ranking."""

    async def create_agent_run(self, run: AgentRun) -> AgentRun:
        """Persist a new autoscroll run."""

    async def update_agent_run(self, run_id: str, fields: dict[str, Any]) -> AgentRun | None:
        """Patch a run and return the updated record when available."""

    async def get_agent_run(self, run_id: str) -> AgentRun | None:
        """Return one agent run."""

    async def insert_queue_items(self, items: list[QueueItem]) -> list[QueueItem]:
        """Persist ready feed items."""

    async def list_ready_queue(
        self, user_id: str, session_id: str, limit: int = 100, run_id: str | None = None
    ) -> list[QueueItem]:
        """Return ready feed items in rank order."""

    async def update_queue_status(self, queue_id: str, status: QueueStatus) -> QueueItem | None:
        """Patch one queued item status."""


class InMemoryContentStore:
    """Process-local store used when Supabase is not configured."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._reactions: dict[str, PostReaction] = {}
        self._runs: dict[str, AgentRun] = {}
        self._queue: dict[str, QueueItem] = {}

    async def insert_reaction(self, reaction: PostReaction) -> PostReaction:
        async with self._lock:
            self._reactions[reaction.reaction_id] = reaction
            return reaction.model_copy(deep=True)

    async def list_preference_reactions(self, user_id: str, limit: int = 500) -> list[PostReaction]:
        async with self._lock:
            reactions = [
                reaction
                for reaction in self._reactions.values()
                if reaction.user_id == user_id and reaction.label in {"hit", "miss"}
            ]
            reactions.sort(key=lambda reaction: reaction.created_at, reverse=True)
            return [reaction.model_copy(deep=True) for reaction in reactions[:limit]]

    async def create_agent_run(self, run: AgentRun) -> AgentRun:
        async with self._lock:
            self._runs[run.run_id] = run
            return run.model_copy(deep=True)

    async def update_agent_run(self, run_id: str, fields: dict[str, Any]) -> AgentRun | None:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            updated = run.model_copy(update=fields)
            self._runs[run_id] = updated
            return updated.model_copy(deep=True)

    async def get_agent_run(self, run_id: str) -> AgentRun | None:
        async with self._lock:
            run = self._runs.get(run_id)
            return run.model_copy(deep=True) if run is not None else None

    async def insert_queue_items(self, items: list[QueueItem]) -> list[QueueItem]:
        async with self._lock:
            for item in items:
                self._queue[item.queue_id] = item
            return [item.model_copy(deep=True) for item in items]

    async def list_ready_queue(
        self, user_id: str, session_id: str, limit: int = 100, run_id: str | None = None
    ) -> list[QueueItem]:
        async with self._lock:
            items = [
                item
                for item in self._queue.values()
                if item.user_id == user_id
                and item.session_id == session_id
                and item.status == "ready"
                and (run_id is None or item.run_id == run_id)
            ]
            items.sort(key=lambda item: (item.rank, item.created_at))
            return [item.model_copy(deep=True) for item in items[:limit]]

    async def update_queue_status(self, queue_id: str, status: QueueStatus) -> QueueItem | None:
        async with self._lock:
            item = self._queue.get(queue_id)
            if item is None:
                return None
            updated = item.model_copy(update={"status": status})
            self._queue[queue_id] = updated
            return updated.model_copy(deep=True)


class SupabaseContentStore:
    """Supabase PostgREST persistence for the autoscroll MVP."""

    def __init__(self, url: str, key: str, timeout_s: float = 10.0) -> None:
        self.base_url = url.rstrip("/")
        self.timeout_s = timeout_s
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def insert_reaction(self, reaction: PostReaction) -> PostReaction:
        rows = await self._request(
            "POST",
            "post_reactions",
            json=self._dump(reaction),
            headers={"Prefer": "return=representation"},
        )
        return PostReaction.model_validate(rows[0])

    async def list_preference_reactions(self, user_id: str, limit: int = 500) -> list[PostReaction]:
        rows = await self._request(
            "GET",
            "post_reactions",
            params={
                "select": "*",
                "user_id": f"eq.{user_id}",
                "label": "in.(hit,miss)",
                "order": "created_at.desc",
                "limit": str(limit),
            },
        )
        return [PostReaction.model_validate(row) for row in rows]

    async def create_agent_run(self, run: AgentRun) -> AgentRun:
        rows = await self._request(
            "POST",
            "agent_runs",
            json=self._dump(run),
            headers={"Prefer": "return=representation"},
        )
        return AgentRun.model_validate(rows[0])

    async def update_agent_run(self, run_id: str, fields: dict[str, Any]) -> AgentRun | None:
        rows = await self._request(
            "PATCH",
            "agent_runs",
            params={"run_id": f"eq.{run_id}"},
            json=self._normalize_json(fields),
            headers={"Prefer": "return=representation"},
        )
        return AgentRun.model_validate(rows[0]) if rows else None

    async def get_agent_run(self, run_id: str) -> AgentRun | None:
        rows = await self._request(
            "GET",
            "agent_runs",
            params={"select": "*", "run_id": f"eq.{run_id}", "limit": "1"},
        )
        return AgentRun.model_validate(rows[0]) if rows else None

    async def insert_queue_items(self, items: list[QueueItem]) -> list[QueueItem]:
        if not items:
            return []
        rows = await self._request(
            "POST",
            "microdose_queue",
            json=[self._dump(item) for item in items],
            headers={"Prefer": "return=representation"},
        )
        return [QueueItem.model_validate(row) for row in rows]

    async def list_ready_queue(
        self, user_id: str, session_id: str, limit: int = 100, run_id: str | None = None
    ) -> list[QueueItem]:
        params = {
            "select": "*",
            "user_id": f"eq.{user_id}",
            "session_id": f"eq.{session_id}",
            "status": "eq.ready",
            "order": "rank.asc",
            "limit": str(limit),
        }
        if run_id is not None:
            params["run_id"] = f"eq.{run_id}"

        rows = await self._request(
            "GET",
            "microdose_queue",
            params=params,
        )
        return [QueueItem.model_validate(row) for row in rows]

    async def update_queue_status(self, queue_id: str, status: QueueStatus) -> QueueItem | None:
        rows = await self._request(
            "PATCH",
            "microdose_queue",
            params={"queue_id": f"eq.{queue_id}"},
            json={"status": status},
            headers={"Prefer": "return=representation"},
        )
        return QueueItem.model_validate(rows[0]) if rows else None

    async def _request(
        self,
        method: str,
        table: str,
        params: dict[str, str] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        request_headers = deepcopy(self.headers)
        if headers:
            request_headers.update(headers)

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.request(
                method,
                f"{self.base_url}/rest/v1/{table}",
                params=params,
                json=json,
                headers=request_headers,
            )
            response.raise_for_status()
            if not response.content:
                return []
            return response.json()

    @staticmethod
    def _dump(model: AgentRun | PostReaction | QueueItem) -> dict[str, Any]:
        return SupabaseContentStore._normalize_json(model.model_dump(mode="json"))

    @staticmethod
    def _normalize_json(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: SupabaseContentStore._normalize_json(inner) for key, inner in value.items()}
        if isinstance(value, list):
            return [SupabaseContentStore._normalize_json(inner) for inner in value]
        return value


def content_store_from_env() -> ContentStore:
    url = os.environ.get(SUPABASE_URL_ENV)
    key = os.environ.get(SUPABASE_SERVICE_KEY_ENV) or os.environ.get(SUPABASE_ANON_KEY_ENV)
    if url and key:
        return SupabaseContentStore(url=url, key=key)
    return InMemoryContentStore()


def finish_fields(status: str, **extra: Any) -> dict[str, Any]:
    fields = {"status": status, "finished_at": utc_now_iso()}
    fields.update(extra)
    return fields
