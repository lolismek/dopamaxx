"""Tests for TRIBE scoring."""

import pytest
from twitter_scorer.models import Tweet
from twitter_scorer.score import score_all, score_tribe


@pytest.fixture
def tweets():
    return [
        Tweet(id="1", text="Breaking news: scientists discover dopamine spike trigger.", author="test", created_at=0.0),
        Tweet(id="2", text="Local man finds lost cat.", author="test", created_at=1.0),
        Tweet(id="3", text="New study shows caffeine boosts focus and alertness.", author="test", created_at=2.0),
    ]


def test_score_tribe_returns_float(tweets):
    score = score_tribe(tweets[0])
    assert isinstance(score, float)


def test_score_all_returns_one_entry_per_tweet(tweets):
    scores = score_all(tweets)
    assert set(scores.keys()) == {"1", "2", "3"}
    for v in scores.values():
        assert isinstance(v, float)


def test_score_deterministic(tweets):
    s1 = score_tribe(tweets[0])
    s2 = score_tribe(tweets[0])
    assert s1 == s2


def test_different_texts_differ(tweets):
    scores = score_all(tweets)
    values = list(scores.values())
    assert not all(v == values[0] for v in values), "all tweets scored identically — backend may be broken"
