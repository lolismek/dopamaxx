"""Tests for session logic (no-EEG path)."""

import asyncio
import pytest
from twitter_scorer.models import Tweet
from twitter_scorer.session import run_session


TWEETS = [
    Tweet(id="1", text="First tweet content here.", author="testuser", created_at=0.0),
    Tweet(id="2", text="Second tweet content here.", author="testuser", created_at=1.0),
]

TRIBE_SCORES = {"1": 0.42, "2": 0.61}


def test_session_no_eeg_returns_session_result():
    # Uses an unreachable ws_url to exercise the no-EEG fallback path
    session = asyncio.run(
        run_session(
            TWEETS,
            TRIBE_SCORES,
            ws_url="ws://127.0.0.1:1",  # nothing listening
            min_display_s=0.0,
        )
    )
    assert session.username == "testuser"
    assert len(session.views) == 2


def test_session_no_eeg_preserves_tribe_scores():
    session = asyncio.run(
        run_session(
            TWEETS,
            TRIBE_SCORES,
            ws_url="ws://127.0.0.1:1",
            min_display_s=0.0,
        )
    )
    score_map = {v.tweet.id: v.tribe_mean for v in session.views}
    assert score_map["1"] == pytest.approx(0.42)
    assert score_map["2"] == pytest.approx(0.61)


def test_session_no_eeg_zero_eeg_fields():
    session = asyncio.run(
        run_session(
            TWEETS,
            TRIBE_SCORES,
            ws_url="ws://127.0.0.1:1",
            min_display_s=0.0,
        )
    )
    for v in session.views:
        assert v.eeg_reward_mean == 0.0
        assert v.eeg_frame_count == 0
