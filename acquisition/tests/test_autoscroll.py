from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from acquisition.autoscroll import AutoscrollService
from acquisition.content_models import AutoscrollStartRequest, PostCandidate, PostReaction, QueueItem
from acquisition.content_store import InMemoryContentStore
from acquisition.scoring import PreferenceScorer
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

    async def fetch_candidates(self, query_context: dict, limit: int) -> list[PostCandidate]:
        assert query_context["agent_mode"] == "locked_in_manual_live_scroll"
        return self.candidates[:limit]


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
    assert payload["reaction"]["embedding"] == [1.0, 0.0]
    assert "raw_eeg" not in payload["reaction"]


def test_autoscroll_ranks_hit_like_candidates_before_miss_like_candidates() -> None:
    asyncio.run(_assert_autoscroll_ranking())


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
        for _ in range(20):
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
        )
    )

    service = AutoscrollService(
        store=store,
        candidate_source=FakeCandidateSource(
            [
                PostCandidate(post_id="sports-1", text="baseball rumors roundup"),
                PostCandidate(post_id="ai-1", text="AI agent research notes"),
            ]
        ),
        embedder=KeywordEmbedder(),
        scorer=PreferenceScorer(),
    )
    run = await service.start(
        AutoscrollStartRequest(user_id="demo-user", session_id="work", target_count=2, timeout_s=2)
    )

    completed = None
    for _ in range(20):
        completed = await store.get_agent_run(run.run_id)
        if completed and completed.status != "running":
            break
        await asyncio.sleep(0.05)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.queued_count == 2

    items = await store.list_ready_queue(user_id="demo-user", session_id="work")
    assert [item.post_id for item in items] == ["ai-1", "sports-1"]
    assert items[0].predicted_reward > items[1].predicted_reward
