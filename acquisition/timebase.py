"""Timebase helpers for DSI-24 live rendering and diagnostics."""

from __future__ import annotations

import time

import numpy as np


def synthetic_relative_time(n_samples: int, sample_rate_hz: float) -> np.ndarray:
    """Return a uniform relative x-axis with the latest sample at t=0."""

    if n_samples <= 0:
        return np.empty((0,), dtype=float)
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be > 0")
    return (np.arange(n_samples, dtype=float) - (n_samples - 1)) / float(sample_rate_hz)


def effective_rate_hz(raw_timestamps: np.ndarray) -> float:
    """Estimate effective rate from raw LSL timestamps."""

    ts = np.asarray(raw_timestamps, dtype=float)
    if ts.size < 2:
        return 0.0
    span = float(ts[-1] - ts[0])
    if not np.isfinite(span) or span <= 0:
        return 0.0
    return float(ts.size / span)


def latest_sample_age_ms(raw_timestamps: np.ndarray, now_s: float | None = None) -> float:
    """Return wall/LSL-clock age for the newest raw timestamp."""

    ts = np.asarray(raw_timestamps, dtype=float)
    if ts.size == 0:
        return float("nan")
    now = current_lsl_time_s() if now_s is None else float(now_s)
    return abs(now - float(ts[-1])) * 1000.0


def current_lsl_time_s() -> float:
    """Return pylsl's local clock when available, with a monotonic fallback."""

    try:
        from pylsl import local_clock
    except ImportError:  # pragma: no cover - environment-specific
        return time.monotonic()
    return float(local_clock())
