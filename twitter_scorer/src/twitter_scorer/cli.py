"""CLI entry point for twitter-scorer."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="twitter-scorer",
        description="Rank Twitter posts by EEG dopamine signal + TRIBE prediction.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # --- score: fetch + TRIBE only, no EEG session ---
    p_score = sub.add_parser("score", help="fetch and TRIBE-score a user's tweets")
    p_score.add_argument("username", help="Twitter username (without @)")
    p_score.add_argument("--limit", type=int, default=50, metavar="N")
    p_score.add_argument("--backend", choices=["fake", "tribe"], default="fake")
    p_score.add_argument("--out", type=Path, metavar="FILE")

    # --- session: full live EEG session ---
    p_session = sub.add_parser(
        "session", help="run a live EEG session over a user's tweets"
    )
    p_session.add_argument("username", help="Twitter username (without @)")
    p_session.add_argument("--limit", type=int, default=20, metavar="N")
    p_session.add_argument("--backend", choices=["fake", "tribe"], default="fake")
    p_session.add_argument(
        "--ws-url", default="ws://localhost:8000/stream/eeg", metavar="URL"
    )
    p_session.add_argument(
        "--min-display-s",
        type=float,
        default=3.0,
        metavar="SECS",
        help="minimum seconds to display each tweet before Enter is accepted",
    )
    p_session.add_argument("--out", type=Path, metavar="FILE")

    # --- rank: re-rank from a saved session JSON ---
    p_rank = sub.add_parser("rank", help="rank tweets from a saved session file")
    p_rank.add_argument("session_file", type=Path)
    p_rank.add_argument("--top", type=int, default=10)

    args = parser.parse_args(argv)

    try:
        if args.cmd == "score":
            return _cmd_score(args)
        if args.cmd == "session":
            return _cmd_session(args)
        if args.cmd == "rank":
            return _cmd_rank(args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


# ---------------------------------------------------------------------------


def _cmd_score(args) -> int:
    from .fetch import fetch_timeline
    from .score import score_all

    print(f"Fetching @{args.username} (limit={args.limit})...")
    tweets = asyncio.run(fetch_timeline(args.username, limit=args.limit))
    print(f"Fetched {len(tweets)} tweets. Scoring ({args.backend})...")

    backend = _make_backend(args.backend)
    scores = score_all(tweets, backend=backend)

    tweet_map = {t.id: t for t in tweets}
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    results = [
        {
            "rank": i + 1,
            "tweet_id": tid,
            "tribe_mean": round(score, 4),
            "text": tweet_map[tid].text,
        }
        for i, (tid, score) in enumerate(ranked)
    ]

    output = json.dumps(results, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(output, encoding="utf-8")
        print(f"Saved to {args.out}")
    else:
        print(output)
    return 0


def _cmd_session(args) -> int:
    from .fetch import fetch_timeline
    from .score import score_all
    from .session import run_session
    from .rank import rank_by_eeg

    print(f"Fetching @{args.username} (limit={args.limit})...")
    tweets = asyncio.run(fetch_timeline(args.username, limit=args.limit))
    print(f"Fetched {len(tweets)} tweets. Scoring ({args.backend})...")

    backend = _make_backend(args.backend)
    tribe_scores = score_all(tweets, backend=backend)

    session = asyncio.run(
        run_session(
            tweets,
            tribe_scores,
            ws_url=args.ws_url,
            min_display_s=args.min_display_s,
        )
    )

    from .rank import rank_by_eeg

    ranked = rank_by_eeg(session)

    print("\n=== Rankings (by EEG reward) ===")
    for r in ranked[:10]:
        marker = " ← top" if r.rank == 1 else ""
        print(
            f"  #{r.rank:2d}  eeg={r.eeg_reward_mean:+.3f}  "
            f"tribe={r.tribe_mean:.3f}  "
            f"{r.text[:72].strip()}...{marker}"
        )

    if args.out:
        payload = {
            "session_id": session.session_id,
            "username": session.username,
            "started_at": session.started_at,
            "views": [dataclasses.asdict(v) for v in session.views],
            "ranked": [dataclasses.asdict(r) for r in ranked],
        }
        args.out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nSaved to {args.out}")

    return 0


def _cmd_rank(args) -> int:
    from .models import SessionResult, Tweet, TweetView
    from .rank import rank_by_eeg

    data = json.loads(args.session_file.read_text(encoding="utf-8"))

    views = []
    for v in data.get("views", []):
        t = v["tweet"]
        views.append(
            TweetView(
                tweet=Tweet(**t),
                tribe_mean=v["tribe_mean"],
                display_start=v["display_start"],
                display_end=v["display_end"],
                eeg_reward_mean=v["eeg_reward_mean"],
                eeg_focus_mean=v["eeg_focus_mean"],
                eeg_frame_count=v["eeg_frame_count"],
            )
        )

    session = SessionResult(
        session_id=data["session_id"],
        username=data.get("username", ""),
        started_at=data.get("started_at", 0.0),
        views=views,
    )

    ranked = rank_by_eeg(session)
    for r in ranked[: args.top]:
        print(
            f"#{r.rank:2d}  eeg={r.eeg_reward_mean:+.3f}  "
            f"tribe={r.tribe_mean:.3f}  "
            f"{r.text[:80]}"
        )
    return 0


def _make_backend(name: str):
    if name == "fake":
        from tribev2_text import DeterministicFakeBackend

        return DeterministicFakeBackend()
    return None  # TribeV2Backend is loaded lazily inside encode_text
