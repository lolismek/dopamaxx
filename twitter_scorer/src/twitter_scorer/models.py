"""Core data structures shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Tweet:
    id: str
    text: str
    author: str
    created_at: float  # unix timestamp


@dataclass
class TweetView:
    """One tweet shown during a session, with TRIBE + EEG scores."""

    tweet: Tweet
    tribe_mean: float
    display_start: float  # time.time() at display
    display_end: float
    eeg_reward_mean: float  # averaged FAA reward score over display window
    eeg_focus_mean: float
    eeg_frame_count: int


@dataclass
class SessionResult:
    session_id: str
    username: str
    started_at: float
    views: list[TweetView] = field(default_factory=list)


@dataclass(frozen=True)
class RankedTweet:
    rank: int
    tweet_id: str
    author: str
    text: str
    eeg_reward_mean: float
    eeg_focus_mean: float
    tribe_mean: float
    display_duration_s: float
    eeg_frame_count: int
