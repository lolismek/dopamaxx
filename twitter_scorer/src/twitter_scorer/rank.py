"""Rank tweet views by EEG reward signal, with TRIBE as secondary sort."""

from __future__ import annotations

from .models import RankedTweet, SessionResult


def rank_by_eeg(session: SessionResult) -> list[RankedTweet]:
    """Return tweets sorted by eeg_reward_mean descending.

    TRIBE activation mean is used as a tiebreaker. When no EEG data was
    collected (eeg_frame_count == 0 for all views) the sort falls back to
    tribe_mean alone so the output is still useful.
    """
    has_eeg = any(v.eeg_frame_count > 0 for v in session.views)

    def sort_key(v):
        if has_eeg:
            return (v.eeg_reward_mean, v.tribe_mean)
        return (v.tribe_mean, 0.0)

    sorted_views = sorted(session.views, key=sort_key, reverse=True)

    return [
        RankedTweet(
            rank=i + 1,
            tweet_id=v.tweet.id,
            author=v.tweet.author,
            text=v.tweet.text,
            eeg_reward_mean=v.eeg_reward_mean,
            eeg_focus_mean=v.eeg_focus_mean,
            tribe_mean=v.tribe_mean,
            display_duration_s=round(v.display_end - v.display_start, 2),
            eeg_frame_count=v.eeg_frame_count,
        )
        for i, v in enumerate(sorted_views)
    ]
