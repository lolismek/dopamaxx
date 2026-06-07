"""Interactive session: display tweets while collecting live EEG frames."""

from __future__ import annotations

import asyncio
import json
import time
import uuid

from .models import SessionResult, Tweet, TweetView


async def run_session(
    tweets: list[Tweet],
    tribe_scores: dict[str, float],
    *,
    ws_url: str = "ws://localhost:8000/stream/eeg",
    min_display_s: float = 3.0,
) -> SessionResult:
    """Show each tweet, collect EEG frames during display, return session.

    Gracefully falls back to tribe-score-only mode when the acquisition
    service is not reachable (e.g. no headset connected).
    """
    session_id = str(uuid.uuid4())[:8]
    started_at = time.time()

    print(f"\n=== DopaMAXX Twitter Session [{session_id}] ===")
    print(f"Connecting to acquisition at {ws_url} ...\n")

    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("websockets required: pip install websockets") from exc

    try:
        async with websockets.connect(ws_url, open_timeout=3) as ws:
            print("EEG connected. Press Enter after reading each tweet.\n")
            views = await _session_with_eeg(tweets, tribe_scores, ws, min_display_s)
    except Exception as exc:
        print(f"WARN: EEG not available ({exc}). Running tribe-score-only mode.\n")
        views = _session_no_eeg(tweets, tribe_scores)

    return SessionResult(
        session_id=session_id,
        username=tweets[0].author if tweets else "",
        started_at=started_at,
        views=views,
    )


async def _session_with_eeg(
    tweets: list[Tweet],
    tribe_scores: dict[str, float],
    ws,
    min_display_s: float,
) -> list[TweetView]:
    loop = asyncio.get_event_loop()
    views: list[TweetView] = []

    for i, tweet in enumerate(tweets, 1):
        _print_tweet(i, len(tweets), tweet)
        display_start = time.time()

        frames = await _collect_until_enter(ws, loop, min_display_s)

        display_end = time.time()
        reward_scores = [
            f["inference"]["reward_score"]
            for f in frames
            if (f.get("inference") or {}).get("reward_score") is not None
        ]
        focus_scores = [
            f["inference"]["focus_score"]
            for f in frames
            if (f.get("inference") or {}).get("focus_score") is not None
        ]

        eeg_reward = _mean(reward_scores)
        eeg_focus = _mean(focus_scores)

        print(
            f"  reward={eeg_reward:+.3f}  focus={eeg_focus:.3f}  "
            f"tribe={tribe_scores.get(tweet.id, 0.0):.3f}  "
            f"frames={len(frames)}\n"
        )

        views.append(
            TweetView(
                tweet=tweet,
                tribe_mean=tribe_scores.get(tweet.id, 0.0),
                display_start=display_start,
                display_end=display_end,
                eeg_reward_mean=round(eeg_reward, 4),
                eeg_focus_mean=round(eeg_focus, 4),
                eeg_frame_count=len(frames),
            )
        )

    return views


async def _collect_until_enter(ws, loop: asyncio.AbstractEventLoop, min_display_s: float) -> list[dict]:
    """Collect WS frames until Enter is pressed (min_display_s enforced)."""
    frames: list[dict] = []
    start = time.time()
    enter_task: asyncio.Future = loop.run_in_executor(None, input, "  [Press Enter to continue] ")

    while True:
        elapsed = time.time() - start
        if enter_task.done() and elapsed >= min_display_s:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.05)
            frames.append(json.loads(raw))
        except asyncio.TimeoutError:
            pass

    if not enter_task.done():
        await enter_task

    return frames


def _session_no_eeg(tweets: list[Tweet], tribe_scores: dict[str, float]) -> list[TweetView]:
    now = time.time()
    return [
        TweetView(
            tweet=t,
            tribe_mean=tribe_scores.get(t.id, 0.0),
            display_start=now,
            display_end=now,
            eeg_reward_mean=0.0,
            eeg_focus_mean=0.0,
            eeg_frame_count=0,
        )
        for t in tweets
    ]


def _print_tweet(index: int, total: int, tweet: Tweet) -> None:
    print(f"[{index}/{total}] @{tweet.author}")
    print("─" * 60)
    print(tweet.text)
    print("─" * 60)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
