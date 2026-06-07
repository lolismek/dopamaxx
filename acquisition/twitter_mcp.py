"""Twitter/X candidate retrieval through a configurable MCP endpoint."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

import httpx

from acquisition.content_models import PostCandidate

TWITTER_MCP_URL_ENV = "DOPAMAXX_TWITTER_MCP_URL"
TWITTER_MCP_FETCH_TOOL_ENV = "DOPAMAXX_TWITTER_MCP_FETCH_TOOL"


class CandidateSource(Protocol):
    async def fetch_candidates(
        self, query_context: dict[str, Any], limit: int
    ) -> list[PostCandidate]:
        """Fetch live candidate posts."""


@dataclass(frozen=True)
class TwitterMCPConfig:
    url: str | None = None
    fetch_tool: str = "twitter.search_candidates"
    timeout_s: float = 3.0
    extra_arguments: dict[str, Any] = field(default_factory=dict)


class TwitterMCPClient:
    """Minimal JSON-RPC MCP client for Twitter/X candidate discovery."""

    def __init__(self, config: TwitterMCPConfig) -> None:
        self.config = config

    async def fetch_candidates(
        self, query_context: dict[str, Any], limit: int
    ) -> list[PostCandidate]:
        if not self.config.url:
            raise RuntimeError(
                f"Twitter MCP is not configured; set {TWITTER_MCP_URL_ENV} to a MCP HTTP endpoint"
            )

        arguments = {
            "query_context": query_context,
            "limit": limit,
            "mode": "live_scroll",
        }
        arguments.update(self.config.extra_arguments)

        body = {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": "tools/call",
            "params": {
                "name": self.config.fetch_tool,
                "arguments": arguments,
            },
        }

        async with httpx.AsyncClient(timeout=self.config.timeout_s) as client:
            response = await client.post(self.config.url, json=body)
            response.raise_for_status()
            payload = response.json()

        if payload.get("error"):
            raise RuntimeError(f"Twitter MCP error: {payload['error']}")

        raw_result = payload.get("result", payload)
        candidates: list[PostCandidate] = []
        for candidate in _extract_posts(raw_result):
            try:
                candidates.append(_coerce_candidate(candidate))
            except ValueError:
                continue
            if len(candidates) >= limit:
                break
        return candidates


def twitter_mcp_from_env() -> TwitterMCPClient:
    return TwitterMCPClient(
        TwitterMCPConfig(
            url=os.environ.get(TWITTER_MCP_URL_ENV),
            fetch_tool=os.environ.get(TWITTER_MCP_FETCH_TOOL_ENV, "twitter.search_candidates"),
        )
    )


def _extract_posts(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        for key in ("posts", "candidates", "items", "tweets"):
            value = payload.get(key)
            if isinstance(value, list):
                return value

        structured = payload.get("structuredContent")
        if structured is not None:
            posts = _extract_posts(structured)
            if posts:
                return posts

        content = payload.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str):
                        try:
                            posts = _extract_posts(json.loads(text))
                        except json.JSONDecodeError:
                            continue
                        if posts:
                            return posts
        elif isinstance(content, str):
            try:
                return _extract_posts(json.loads(content))
            except json.JSONDecodeError:
                return []

    return []


def _coerce_candidate(raw: Any) -> PostCandidate:
    if not isinstance(raw, dict):
        raise ValueError("candidate post must be an object")

    post_id = (
        raw.get("post_id")
        or raw.get("tweet_id")
        or raw.get("id")
        or raw.get("url")
        or raw.get("permalink")
    )
    if not post_id:
        raise ValueError("candidate post is missing post_id/id/url")

    media = raw.get("media_urls") or raw.get("media") or []
    if isinstance(media, str):
        media_urls = [media]
    elif isinstance(media, list):
        media_urls = [str(item) for item in media]
    else:
        media_urls = []

    return PostCandidate(
        post_id=str(post_id),
        text=str(raw.get("text") or raw.get("body") or raw.get("content") or ""),
        author=raw.get("author") or raw.get("username") or raw.get("handle"),
        url=raw.get("url") or raw.get("permalink"),
        media_urls=media_urls,
        created_at=raw.get("created_at"),
        source="twitter_mcp",
        metadata={key: value for key, value in raw.items() if key not in {"media_urls", "media"}},
    )
