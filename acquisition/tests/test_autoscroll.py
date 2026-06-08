from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from acquisition.autoscroll import AutoscrollService
from acquisition.content_models import AutoscrollStartRequest, PostCandidate, PostReaction, QueueItem
from acquisition.content_store import InMemoryContentStore, SupabaseContentStore
from acquisition.service import create_app


class FakeRuntime:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def health(self) -> dict:
        return {"status": "connected"}

    def metadata(self) -> dict:
        return {}

    def inject(self, _request) -> dict:
        return {"ok": True}

    def frame(self) -> dict:
        return {}


class KeywordEmbedder:
    async def embed_post(self, post: PostCandidate) -> list[float]:
        text = post.text.lower()
        if "ai" in text or "machine" in text:
            return [1.0, 0.0]
        return [0.0, 1.0]


class FakeCandidateSource:
    def __init__(self, candidates: list[PostCandidate]) -> None:
        self.candidates = candidates
        self.query_context: dict | None = None

    async def fetch_candidates(self, query_context: dict, limit: int) -> list[PostCandidate]:
        assert query_context["agent_mode"] == "locked_in_manual_live_scroll"
        self.query_context = query_context
        return self.candidates[:limit]


class FailingCandidateSource:
    async def fetch_candidates(self, query_context: dict, limit: int) -> list[PostCandidate]:
        raise RuntimeError("fallback should not be required")


def test_locked_out_reaction_endpoint_stores_derived_hit_label() -> None:
    store = InMemoryContentStore()
    app = create_app(
        FakeRuntime(),
        content_store=store,
        candidate_source=FakeCandidateSource([]),
        embedder=KeywordEmbedder(),
    )

    with TestClient(app) as client:
        response = client.post(
            "/locked-out/reactions",
            json={
                "user_id": "demo-user",
                "session_id": "demo-session",
                "post": {"post_id": "post-1", "text": "AI research thread"},
                "reward_score": 0.8,
                "focus_score": 0.6,
                "dwell_ms": 1400,
                "eeg_features": {"faa": 0.7, "beta_bump": 0.2},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reaction"]["label"] == "hit"
    assert payload["reaction"]["embedding"] == []
    assert "raw_eeg" not in payload["reaction"]


def test_autoscroll_queues_source_order_without_reward_matching() -> None:
    asyncio.run(_assert_autoscroll_ranking())


def test_autoscroll_compiles_twenty_timer_demo_recommendations() -> None:
    asyncio.run(_assert_autoscroll_compiles_twenty_recommendations())


def test_supabase_store_reads_locked_out_observations_as_preference_reactions() -> None:
    async def _assert() -> None:
        store = SupabaseContentStore(url="https://example.supabase.co", key="test-key")

        async def fake_request(method, table, params=None, json=None, headers=None):
            assert method == "GET"
            assert params["user_id"] == "eq.demo-user"
            assert "label" not in params
            assert "reward_label" not in params
            if table == "post_reactions":
                return []
            if table == "post_observations":
                return [
                    {
                        "id": "obs-1",
                        "user_id": "demo-user",
                        "session_id": "locked-out-session",
                        "reward_score": 0.0,
                        "reward_label": "neutral",
                        "focus_score": 0.61,
                        "dwell_ms": 1400,
                        "observed_at": "2026-06-07T12:00:00+00:00",
                        "posts": {
                            "id": "post-row-1",
                            "platform_post_id": "tweet-1",
                            "canonical_url": "https://x.com/example/status/tweet-1",
                            "author_handle": "example",
                            "author_name": "Example",
                            "text": "AI agents are getting useful",
                            "media": [{"src": "https://example.test/image.png"}],
                            "embedding": None,
                            "embedding_status": "pending",
                        },
                    }
                ]
            raise AssertionError(f"unexpected table {table}")

        store._request = fake_request
        reactions = await store.list_preference_reactions("demo-user")

        assert len(reactions) == 1
        reaction = reactions[0]
        assert reaction.post_id == "tweet-1"
        assert reaction.label == "neutral"
        assert reaction.reward_score == 0.0
        assert reaction.focus_score == 0.61
        assert reaction.embedding == []
        assert reaction.media_urls == ["https://example.test/image.png"]
        assert reaction.metadata["source"] == "locked_out_capture"

    asyncio.run(_assert())


def test_microdose_feed_can_be_filtered_to_one_run() -> None:
    store = InMemoryContentStore()
    asyncio.run(
        store.insert_queue_items(
            [
                QueueItem(
                    run_id="run-old",
                    user_id="demo-user",
                    session_id="demo-session",
                    post_id="old-post",
                    text="old queued post",
                    predicted_reward=0.1,
                    rank=1,
                ),
                QueueItem(
                    run_id="run-new",
                    user_id="demo-user",
                    session_id="demo-session",
                    post_id="new-post",
                    text="new queued post",
                    predicted_reward=0.9,
                    rank=1,
                ),
            ]
        )
    )
    app = create_app(
        FakeRuntime(),
        content_store=store,
        candidate_source=FakeCandidateSource([]),
        embedder=KeywordEmbedder(),
    )

    with TestClient(app) as client:
        response = client.get(
            "/feed/microdose",
            params={
                "user_id": "demo-user",
                "session_id": "demo-session",
                "run_id": "run-new",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert [item["post_id"] for item in payload["items"]] == ["new-post"]


def test_microdose_feed_page_serves_x_embed_shell() -> None:
    app = create_app(
        FakeRuntime(),
        content_store=InMemoryContentStore(),
        candidate_source=FakeCandidateSource([]),
        embedder=KeywordEmbedder(),
    )

    with TestClient(app) as client:
        response = client.get("/microdose/feed?user_id=demo-user&session_id=demo-session")

    assert response.status_code == 200
    assert "https://platform.twitter.com/widgets.js" in response.text
    assert 'new URL("/feed/microdose", window.location.origin)' in response.text
    assert "widgets.createTweet" in response.text


def test_autoscroll_prefers_buffered_for_you_candidates() -> None:
    store = InMemoryContentStore()
    asyncio.run(
        store.insert_reaction(
            PostReaction(
                user_id="demo-user",
                session_id="locked-out",
                post_id="hit-1",
                text="AI machine learning systems",
                embedding=[1.0, 0.0],
                reward_score=0.9,
                label="hit",
                dwell_ms=1600,
                created_at=iso_seconds_ago(60),
            )
        )
    )
    app = create_app(
        FakeRuntime(),
        content_store=store,
        candidate_source=FakeCandidateSource(
            [PostCandidate(post_id="fallback-1", text="fallback search candidate")]
        ),
        embedder=KeywordEmbedder(),
    )

    with TestClient(app) as client:
        ingest = client.post(
            "/feed/for-you/candidates",
            json={
                "user_id": "demo-user",
                "session_id": "demo-session",
                "posts": [
                    {
                        "post_id": "for-you-1",
                        "text": "AI post from the visible For You feed",
                        "author": "casperdongg",
                        "url": "https://x.com/casperdongg/status/1",
                        "source": "x_for_you_extension",
                    }
                ],
            },
        )
        assert ingest.status_code == 200
        assert ingest.json()["buffered_count"] == 1

        start = client.post(
            "/agent/autoscroll/start",
            json={
                "user_id": "demo-user",
                "session_id": "demo-session",
                "target_count": 1,
                "timeout_s": 2,
                "query_context": {"candidate_source": "x_for_you"},
            },
        )
        assert start.status_code == 200
        run_id = start.json()["run"]["run_id"]

        completed = None
        for _ in range(60):
            completed = client.get(f"/agent/autoscroll/runs/{run_id}").json()["run"]
            if completed["status"] != "running":
                break
            asyncio.run(asyncio.sleep(0.05))

        assert completed is not None
        assert completed["status"] == "completed"

        feed = client.get(
            "/feed/microdose",
            params={
                "user_id": "demo-user",
                "session_id": "demo-session",
                "run_id": run_id,
            },
        )

    assert feed.status_code == 200
    assert [item["post_id"] for item in feed.json()["items"]] == ["for-you-1"]


def test_autoscroll_completes_from_buffered_candidates_without_twitter_mcp() -> None:
    store = InMemoryContentStore()
    app = create_app(
        FakeRuntime(),
        content_store=store,
        candidate_source=FailingCandidateSource(),
        embedder=KeywordEmbedder(),
    )

    with TestClient(app) as client:
        ingest = client.post(
            "/feed/for-you/candidates",
            json={
                "user_id": "demo-user",
                "session_id": "demo-session",
                "posts": [
                    {
                        "post_id": f"for-you-{index}",
                        "text": f"AI agent post from the visible For You feed {index}",
                        "author": "ai_lab",
                        "url": f"https://x.com/ai_lab/status/{index}",
                        "source": "x_for_you_extension",
                    }
                    for index in range(20)
                ],
            },
        )
        assert ingest.status_code == 200

        start = client.post(
            "/agent/autoscroll/start",
            json={
                "user_id": "demo-user",
                "session_id": "demo-session",
                "target_count": 20,
                "timeout_s": 2,
                "query_context": {"candidate_source": "x_for_you"},
            },
        )
        assert start.status_code == 200
        run_id = start.json()["run"]["run_id"]

        completed = None
        for _ in range(60):
            completed = client.get(f"/agent/autoscroll/runs/{run_id}").json()["run"]
            if completed["status"] != "running":
                break
            asyncio.run(asyncio.sleep(0.05))

        feed = client.get(
            "/feed/microdose",
            params={
                "user_id": "demo-user",
                "session_id": "demo-session",
                "run_id": run_id,
                "limit": 25,
            },
        )

    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["queued_count"] == 20
    assert feed.status_code == 200
    assert len(feed.json()["items"]) == 20


def test_strict_for_you_autoscroll_does_not_fall_back_to_twitter_search() -> None:
    store = InMemoryContentStore()
    app = create_app(
        FakeRuntime(),
        content_store=store,
        candidate_source=FakeCandidateSource(
            [PostCandidate(post_id="fallback-1", text="AI agent infrastructure for startups")]
        ),
        embedder=KeywordEmbedder(),
    )

    with TestClient(app) as client:
        reaction = client.post(
            "/locked-out/reactions",
            json={
                "user_id": "demo-user",
                "session_id": "locked-out",
                "post": {"post_id": "interest-1", "text": "AI agent infrastructure for startups"},
                "reward_score": 0.0,
                "focus_score": 0.6,
                "dwell_ms": 8000,
                "eeg_features": {},
            },
        )
        assert reaction.status_code == 200

        start = client.post(
            "/agent/autoscroll/start",
            json={
                "user_id": "demo-user",
                "session_id": "demo-session",
                "target_count": 1,
                "timeout_s": 1,
                "query_context": {
                    "candidate_source": "x_for_you",
                    "for_you_only": True,
                    "recent_activity_window_s": 0,
                    "require_interest_profile": True,
                },
            },
        )
        assert start.status_code == 200
        run_id = start.json()["run"]["run_id"]

        completed = None
        for _ in range(60):
            completed = client.get(f"/agent/autoscroll/runs/{run_id}").json()["run"]
            if completed["status"] != "running":
                break
            asyncio.run(asyncio.sleep(0.05))

        feed = client.get(
            "/feed/microdose",
            params={
                "user_id": "demo-user",
                "session_id": "demo-session",
                "run_id": run_id,
            },
        )

    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["queued_count"] == 0
    assert feed.status_code == 200
    assert feed.json()["items"] == []


def test_autoscroll_allows_non_startup_candidates_without_reward_matching() -> None:
    asyncio.run(_assert_autoscroll_allows_non_startup_candidates())


def test_autoscroll_seeds_recent_engaged_posts_from_activity_window() -> None:
    asyncio.run(_assert_autoscroll_seeds_recent_engaged_posts())


def test_extension_queues_source_interest_post_from_activity_window() -> None:
    asyncio.run(_assert_extension_queues_source_interest_post_from_activity_window())

    repo_root = Path(__file__).resolve().parents[2]
    background_js = (repo_root / "extension" / "background.js").read_text()
    assert "include_recent_activity_candidates: true" in background_js
    assert "allow_relaxed_candidate_fill: true" in background_js
    assert "for_you_only: false" in background_js
    assert "timeout_s: 15" in background_js


def test_autoscroll_fills_remaining_slots_after_strict_matches() -> None:
    asyncio.run(_assert_autoscroll_fills_remaining_slots_after_strict_matches())


def test_autoscroll_filters_buffered_for_you_to_recent_activity_window() -> None:
    store = InMemoryContentStore()
    app = create_app(
        FakeRuntime(),
        content_store=store,
        candidate_source=FailingCandidateSource(),
        embedder=KeywordEmbedder(),
    )

    with TestClient(app) as client:
        old_ingest = client.post(
            "/feed/for-you/candidates",
            json={
                "user_id": "demo-user",
                "session_id": "demo-session",
                "observed_at": iso_seconds_ago(35),
                "posts": [
                    {
                        "post_id": "old-buffered",
                        "text": "old buffered post",
                        "url": "https://x.com/demo/status/old",
                        "source": "x_for_you_extension",
                    }
                ],
            },
        )
        recent_ingest = client.post(
            "/feed/for-you/candidates",
            json={
                "user_id": "demo-user",
                "session_id": "demo-session",
                "observed_at": iso_seconds_ago(5),
                "posts": [
                    {
                        "post_id": "recent-buffered",
                        "text": "recent buffered post",
                        "url": "https://x.com/demo/status/recent",
                        "source": "x_for_you_extension",
                    }
                ],
            },
        )
        assert old_ingest.status_code == 200
        assert recent_ingest.status_code == 200

        start = client.post(
            "/agent/autoscroll/start",
            json={
                "user_id": "demo-user",
                "session_id": "demo-session",
                "target_count": 1,
                "timeout_s": 2,
                "query_context": {
                    "candidate_source": "x_for_you",
                    "recent_activity_window_s": 20,
                },
            },
        )
        assert start.status_code == 200
        run_id = start.json()["run"]["run_id"]

        completed = None
        for _ in range(20):
            completed = client.get(f"/agent/autoscroll/runs/{run_id}").json()["run"]
            if completed["status"] != "running":
                break
            asyncio.run(asyncio.sleep(0.05))

        feed = client.get(
            "/feed/microdose",
            params={
                "user_id": "demo-user",
                "session_id": "demo-session",
                "run_id": run_id,
            },
        )

    assert completed is not None
    assert completed["status"] == "completed"
    assert feed.status_code == 200
    assert [item["post_id"] for item in feed.json()["items"]] == ["recent-buffered"]
    assert "refreshed_at" in feed.json()


def test_autoscroll_filters_candidates_to_engaged_post_type() -> None:
    asyncio.run(_assert_autoscroll_filters_to_long_dwell_type())


def test_autoscroll_rejects_generic_keyword_matches() -> None:
    asyncio.run(_assert_autoscroll_rejects_generic_keyword_matches())


def test_autoscroll_requires_engaged_profile_when_requested() -> None:
    asyncio.run(_assert_autoscroll_requires_long_dwell_profile())


async def _assert_autoscroll_ranking() -> None:
    store = InMemoryContentStore()
    await store.insert_reaction(
        PostReaction(
            user_id="demo-user",
            session_id="locked-out",
            post_id="hit-1",
            text="AI machine learning systems",
            embedding=[1.0, 0.0],
            reward_score=0.9,
            label="hit",
            dwell_ms=1600,
            created_at=iso_seconds_ago(60),
        )
    )
    await store.insert_reaction(
        PostReaction(
            user_id="demo-user",
            session_id="locked-out",
            post_id="miss-1",
            text="baseball trade rumors",
            embedding=[0.0, 1.0],
            reward_score=-0.8,
            label="miss",
            dwell_ms=1600,
            created_at=iso_seconds_ago(60),
        )
    )

    service = AutoscrollService(
        store=store,
        candidate_source=FakeCandidateSource(
            [
                PostCandidate(post_id="sports-1", text="baseball rumors roundup"),
                PostCandidate(post_id="ai-1", text="AI agent research notes"),
                PostCandidate(post_id="ai-2", text="machine learning notes"),
            ]
        ),
        embedder=KeywordEmbedder(),
    )
    run = await service.start(
        AutoscrollStartRequest(user_id="demo-user", session_id="work", target_count=2, timeout_s=2)
    )

    completed = None
    for _ in range(60):
        completed = await store.get_agent_run(run.run_id)
        if completed and completed.status != "running":
            break
        await asyncio.sleep(0.05)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.queued_count == 2

    items = await store.list_ready_queue(user_id="demo-user", session_id="work")
    assert [item.post_id for item in items] == ["sports-1", "ai-1"]
    assert all(item.predicted_reward > 0 for item in items)
    assert all("no engaged-post signal yet" in (item.rationale or "") for item in items)


async def _assert_autoscroll_compiles_twenty_recommendations() -> None:
    store = InMemoryContentStore()

    service = AutoscrollService(
        store=store,
        candidate_source=FakeCandidateSource(
            [
                PostCandidate(post_id=f"ai-{index}", text=f"AI agent research note {index}")
                for index in range(25)
            ]
        ),
        embedder=KeywordEmbedder(),
    )
    run = await service.start(
        AutoscrollStartRequest(user_id="demo-user", session_id="work", target_count=20, timeout_s=2)
    )

    completed = None
    for _ in range(60):
        completed = await store.get_agent_run(run.run_id)
        if completed and completed.status != "running":
            break
        await asyncio.sleep(0.05)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.queued_count == 20

    items = await store.list_ready_queue(user_id="demo-user", session_id="work", limit=25)
    assert len(items) == 20
    assert [item.rank for item in items] == list(range(1, 21))
    assert all(item.predicted_reward == 0.5 for item in items)


async def _assert_autoscroll_allows_non_startup_candidates() -> None:
    store = InMemoryContentStore()
    await store.insert_reaction(
        PostReaction(
            user_id="demo-user",
            session_id="locked-out",
            post_id="hit-1",
            text="AI machine learning systems",
            embedding=[1.0, 0.0],
            reward_score=0.9,
            label="hit",
            dwell_ms=1600,
            created_at=iso_seconds_ago(60),
        )
    )

    service = AutoscrollService(
        store=store,
        candidate_source=FakeCandidateSource(
            [PostCandidate(post_id="ai-1", text="AI agent research notes")]
        ),
        embedder=KeywordEmbedder(),
    )
    run = await service.start(
        AutoscrollStartRequest(user_id="demo-user", session_id="work", target_count=1, timeout_s=2)
    )

    completed = None
    for _ in range(60):
        completed = await store.get_agent_run(run.run_id)
        if completed and completed.status != "running":
            break
        await asyncio.sleep(0.05)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.queued_count == 1
    assert completed.error is None

    items = await store.list_ready_queue(user_id="demo-user", session_id="work")
    assert [item.post_id for item in items] == ["ai-1"]


async def _assert_autoscroll_seeds_recent_engaged_posts() -> None:
    store = InMemoryContentStore()
    await store.insert_reaction(
        PostReaction(
            user_id="demo-user",
            session_id="locked-out",
            post_id="recent-engaged",
            text="recent engaged post",
            author="demo",
            url="https://x.com/demo/status/recent-engaged",
            embedding=[],
            reward_score=0.0,
            label="neutral",
            dwell_ms=8000,
            created_at=iso_seconds_ago(10),
        )
    )
    await store.insert_reaction(
        PostReaction(
            user_id="demo-user",
            session_id="locked-out",
            post_id="stale-engaged",
            text="stale engaged post",
            embedding=[],
            reward_score=0.0,
            label="neutral",
            dwell_ms=3000,
            created_at=iso_seconds_ago(45),
        )
    )

    service = AutoscrollService(
        store=store,
        candidate_source=FailingCandidateSource(),
        embedder=KeywordEmbedder(),
    )
    run = await service.start(
        AutoscrollStartRequest(
            user_id="demo-user",
            session_id="work",
            target_count=1,
            timeout_s=2,
            query_context={
                "recent_activity_window_s": 20,
                "include_recent_activity_candidates": True,
            },
        )
    )

    completed = None
    for _ in range(60):
        completed = await store.get_agent_run(run.run_id)
        if completed and completed.status != "running":
            break
        await asyncio.sleep(0.05)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.queued_count == 1

    items = await store.list_ready_queue(user_id="demo-user", session_id="work")
    assert [item.post_id for item in items] == ["recent-engaged"]
    assert items[0].metadata["source"] == "locked_out_recent_activity"
    assert items[0].predicted_reward == 1.0


async def _assert_extension_queues_source_interest_post_from_activity_window() -> None:
    store = InMemoryContentStore()
    await store.insert_reaction(
        PostReaction(
            user_id="demo-user",
            session_id="locked-out",
            post_id="source-interest",
            text="AI agent infrastructure startup founder tools",
            embedding=[],
            reward_score=0.4,
            label="hit",
            dwell_ms=8200,
            created_at=iso_seconds_ago(2),
        )
    )

    service = AutoscrollService(
        store=store,
        candidate_source=FakeCandidateSource(
            [
                PostCandidate(post_id="unrelated-1", text="baseball pitching rumors"),
                PostCandidate(post_id="related-1", text="AI agent startup infrastructure tools"),
            ]
        ),
        embedder=KeywordEmbedder(),
    )
    run = await service.start(
        AutoscrollStartRequest(
            user_id="demo-user",
            session_id="work",
            target_count=1,
            timeout_s=2,
            query_context={
                "candidate_source": "x_for_you",
                "recent_activity_window_s": 20,
                "require_interest_profile": True,
                "for_you_only": True,
                "include_recent_activity_candidates": True,
            },
        )
    )

    completed = None
    for _ in range(60):
        completed = await store.get_agent_run(run.run_id)
        if completed and completed.status != "running":
            break
        await asyncio.sleep(0.05)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.queued_count == 1

    items = await store.list_ready_queue(user_id="demo-user", session_id="work")
    assert [item.post_id for item in items] == ["source-interest"]
    assert items[0].metadata["source"] == "locked_out_recent_activity"
    assert "type match" in (items[0].rationale or "")


async def _assert_autoscroll_fills_remaining_slots_after_strict_matches() -> None:
    store = InMemoryContentStore()
    await store.insert_reaction(
        PostReaction(
            user_id="demo-user",
            session_id="locked-out",
            post_id="interest-ai",
            text="AI agent infrastructure startup founder tools",
            embedding=[],
            reward_score=0.4,
            label="hit",
            dwell_ms=4200,
            created_at=iso_seconds_ago(30),
        )
    )

    service = AutoscrollService(
        store=store,
        candidate_source=FakeCandidateSource(
            [
                PostCandidate(post_id="strict-1", text="AI agent startup infrastructure"),
                PostCandidate(post_id="fill-1", text="venture capital founder story"),
                PostCandidate(post_id="fill-2", text="product launch thread"),
            ]
        ),
        embedder=KeywordEmbedder(),
    )
    run = await service.start(
        AutoscrollStartRequest(
            user_id="demo-user",
            session_id="work",
            target_count=3,
            timeout_s=2,
            query_context={
                "require_interest_profile": True,
                "include_recent_activity_candidates": False,
            },
        )
    )

    completed = None
    for _ in range(60):
        completed = await store.get_agent_run(run.run_id)
        if completed and completed.status != "running":
            break
        await asyncio.sleep(0.05)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.queued_count == 3

    items = await store.list_ready_queue(user_id="demo-user", session_id="work", limit=3)
    assert [item.post_id for item in items] == ["strict-1", "fill-1", "fill-2"]
    assert "type match" in (items[0].rationale or "")
    assert all("relaxed fill" in (item.rationale or "") for item in items[1:])
    assert all(item.predicted_reward < items[0].predicted_reward for item in items[1:])


async def _assert_autoscroll_filters_to_long_dwell_type() -> None:
    store = InMemoryContentStore()
    await store.insert_reaction(
        PostReaction(
            user_id="demo-user",
            session_id="locked-out",
            post_id="interest-ai",
            text="AI agents and machine learning startup tooling",
            embedding=[],
            reward_score=0.0,
            label="neutral",
            dwell_ms=8200,
            created_at=iso_seconds_ago(60),
        )
    )

    service = AutoscrollService(
        store=store,
        candidate_source=FakeCandidateSource(
            [
                PostCandidate(post_id="sports-1", text="baseball rumors roundup"),
                PostCandidate(post_id="single-ai", text="AI memes"),
                PostCandidate(
                    post_id="author-false-positive",
                    text="random topic",
                    author="machine learning startup",
                ),
                PostCandidate(post_id="ai-1", text="AI agent infrastructure for startups"),
                PostCandidate(post_id="ml-1", text="machine learning founder notes"),
            ]
        ),
        embedder=KeywordEmbedder(),
    )
    run = await service.start(
        AutoscrollStartRequest(user_id="demo-user", session_id="work", target_count=2, timeout_s=2)
    )

    completed = None
    for _ in range(60):
        completed = await store.get_agent_run(run.run_id)
        if completed and completed.status != "running":
            break
        await asyncio.sleep(0.05)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.queued_count == 2

    items = await store.list_ready_queue(user_id="demo-user", session_id="work")
    assert [item.post_id for item in items] == ["ai-1", "ml-1"]
    assert all("type match" in (item.rationale or "") for item in items)


async def _assert_autoscroll_rejects_generic_keyword_matches() -> None:
    store = InMemoryContentStore()
    await store.insert_reaction(
        PostReaction(
            user_id="demo-user",
            session_id="locked-out",
            post_id="interest-box",
            text=(
                "Box now has a markdown editor on the web. Full CLI support. "
                "Commenting. Full version history. Box Drive connects desktop clients."
            ),
            embedding=[],
            reward_score=0.0,
            label="neutral",
            dwell_ms=8200,
            created_at=iso_seconds_ago(60),
        )
    )

    service = AutoscrollService(
        store=store,
        candidate_source=FakeCandidateSource(
            [
                PostCandidate(post_id="generic-1", text="full version game content update"),
                PostCandidate(post_id="box-1", text="Box markdown editor CLI support ships"),
            ]
        ),
        embedder=KeywordEmbedder(),
    )
    run = await service.start(
        AutoscrollStartRequest(user_id="demo-user", session_id="work", target_count=1, timeout_s=2)
    )

    completed = None
    for _ in range(60):
        completed = await store.get_agent_run(run.run_id)
        if completed and completed.status != "running":
            break
        await asyncio.sleep(0.05)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.queued_count == 1

    items = await store.list_ready_queue(user_id="demo-user", session_id="work")
    assert [item.post_id for item in items] == ["box-1"]
    assert "full" not in (items[0].rationale or "")
    assert "version" not in (items[0].rationale or "")


async def _assert_autoscroll_requires_long_dwell_profile() -> None:
    store = InMemoryContentStore()
    service = AutoscrollService(
        store=store,
        candidate_source=FailingCandidateSource(),
        embedder=KeywordEmbedder(),
    )
    run = await service.start(
        AutoscrollStartRequest(
            user_id="demo-user",
            session_id="work",
            target_count=1,
            timeout_s=1,
            query_context={"require_interest_profile": True},
        )
    )

    completed = None
    for _ in range(60):
        completed = await store.get_agent_run(run.run_id)
        if completed and completed.status != "running":
            break
        await asyncio.sleep(0.05)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.queued_count == 0
    assert completed.error == "no engaged-post signal was available before the run expired"

    items = await store.list_ready_queue(user_id="demo-user", session_id="work")
    assert items == []


def iso_seconds_ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
