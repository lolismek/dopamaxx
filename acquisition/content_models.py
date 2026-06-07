"""Content and autoscroll data contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ReactionLabel = Literal["hit", "miss", "neutral"]
QueueStatus = Literal["ready", "shown", "dismissed", "consumed"]
AgentRunStatus = Literal["running", "completed", "cancelled", "failed"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostCandidate(BaseModel):
    post_id: str = Field(min_length=1)
    text: str = ""
    author: str | None = None
    url: str | None = None
    media_urls: list[str] = Field(default_factory=list)
    created_at: str | None = None
    source: str = "twitter_mcp"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReactionIngestRequest(BaseModel):
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    post: PostCandidate
    reward_score: float = Field(ge=-1.0, le=1.0)
    focus_score: float | None = None
    dwell_ms: int = Field(ge=0)
    label: ReactionLabel | None = None
    eeg_features: dict[str, float] = Field(default_factory=dict)

    def resolved_label(self, hit_threshold: float, miss_threshold: float) -> ReactionLabel:
        if self.label is not None:
            return self.label
        if self.reward_score >= hit_threshold:
            return "hit"
        if self.reward_score <= miss_threshold:
            return "miss"
        return "neutral"


class PostReaction(BaseModel):
    reaction_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    session_id: str
    post_id: str
    text: str
    author: str | None = None
    url: str | None = None
    media_urls: list[str] = Field(default_factory=list)
    embedding: list[float] = Field(default_factory=list)
    reward_score: float
    focus_score: float | None = None
    label: ReactionLabel
    dwell_ms: int
    eeg_features: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class AutoscrollStartRequest(BaseModel):
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    target_count: int = Field(default=20, ge=1, le=100)
    timeout_s: float = Field(default=45.0, gt=0, le=300)
    query_context: dict[str, Any] = Field(default_factory=dict)


class AutoscrollCancelRequest(BaseModel):
    run_id: str = Field(min_length=1)


class AgentRun(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    session_id: str
    status: AgentRunStatus = "running"
    target_count: int = 20
    queued_count: int = 0
    fetched_count: int = 0
    accepted_count: int = 0
    error: str | None = None
    started_at: str = Field(default_factory=utc_now_iso)
    finished_at: str | None = None


class QueueItem(BaseModel):
    queue_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    user_id: str
    session_id: str
    post_id: str
    text: str
    author: str | None = None
    url: str | None = None
    media_urls: list[str] = Field(default_factory=list)
    predicted_reward: float
    rank: int
    status: QueueStatus = "ready"
    rationale: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class QueueStatusUpdateRequest(BaseModel):
    status: QueueStatus
