"""TRIBE v2 activation scoring for tweets."""

from __future__ import annotations

from .models import Tweet


def score_tribe(tweet: Tweet, backend=None) -> float:
    """Return TRIBE activation_summary.mean for a single tweet."""
    try:
        from tribev2_text import encode_text, DeterministicFakeBackend
    except ImportError as exc:
        raise RuntimeError(
            "tribev2_text is required. Install it with:\n"
            "  pip install -e ../tribev2_text"
        ) from exc

    effective_backend = backend if backend is not None else DeterministicFakeBackend()
    sig = encode_text(tweet.text, backend=effective_backend)
    return sig.activation_summary.mean


def score_all(tweets: list[Tweet], backend=None) -> dict[str, float]:
    """Return {tweet_id: tribe_mean} for all tweets."""
    return {t.id: score_tribe(t, backend=backend) for t in tweets}
