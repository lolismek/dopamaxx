"""Tests for ranking logic."""

import time
import pytest
from twitter_scorer.models import SessionResult, Tweet, TweetView
from twitter_scorer.rank import rank_by_eeg


def _make_session(reward_scores: list[float]) -> SessionResult:
    now = time.time()
    views = [
        TweetView(
            tweet=Tweet(id=str(i), text=f"tweet {i}", author="test", created_at=float(i)),
            tribe_mean=0.1 * i,
            display_start=now,
            display_end=now + 5.0,
            eeg_reward_mean=score,
            eeg_focus_mean=0.5,
            eeg_frame_count=50,
        )
        for i, score in enumerate(reward_scores)
    ]
    return SessionResult(session_id="test", username="test", started_at=now, views=views)


def test_rank_sorts_by_eeg_reward_descending():
    session = _make_session([0.1, 0.9, 0.3, 0.7])
    ranked = rank_by_eeg(session)
    assert [r.eeg_reward_mean for r in ranked] == [0.9, 0.7, 0.3, 0.1]


def test_rank_assigns_sequential_ranks():
    session = _make_session([0.5, 0.2, 0.8])
    ranked = rank_by_eeg(session)
    assert [r.rank for r in ranked] == [1, 2, 3]


def test_rank_no_eeg_falls_back_to_tribe():
    now = time.time()
    views = [
        TweetView(
            tweet=Tweet(id=str(i), text=f"tweet {i}", author="test", created_at=float(i)),
            tribe_mean=score,
            display_start=now,
            display_end=now,
            eeg_reward_mean=0.0,
            eeg_focus_mean=0.0,
            eeg_frame_count=0,  # no EEG
        )
        for i, score in enumerate([0.2, 0.8, 0.5])
    ]
    session = SessionResult(session_id="x", username="test", started_at=now, views=views)
    ranked = rank_by_eeg(session)
    assert ranked[0].tribe_mean == 0.8
    assert ranked[1].tribe_mean == 0.5


def test_rank_duration_computed_correctly():
    now = time.time()
    view = TweetView(
        tweet=Tweet(id="1", text="hi", author="test", created_at=0.0),
        tribe_mean=0.5,
        display_start=now,
        display_end=now + 7.25,
        eeg_reward_mean=0.4,
        eeg_focus_mean=0.6,
        eeg_frame_count=72,
    )
    session = SessionResult(session_id="x", username="test", started_at=now, views=[view])
    ranked = rank_by_eeg(session)
    assert ranked[0].display_duration_s == 7.25
