"""WebSocket frame construction for live EEG windows."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from acquisition.quality import quality_flags
from acquisition.ring_buffer import RingBuffer
from acquisition.spec import CHANNEL_LABELS, SAMPLE_RATE_HZ, STREAM_NAME
from acquisition.timebase import effective_rate_hz, latest_sample_age_ms, synthetic_relative_time


@dataclass(frozen=True)
class FrameMetadata:
    stream_name: str = STREAM_NAME
    channel_labels: tuple[str, ...] = CHANNEL_LABELS
    sample_rate_hz: float = SAMPLE_RATE_HZ
    source_mode: str = "unknown"
    connection_status: str = "starting"
    message: str | None = None


def build_eeg_frame(
    ring: RingBuffer,
    metadata: FrameMetadata,
    window_s: float = 5.0,
    max_points: int = 900,
) -> dict:
    """Build the JSON-serializable live EEG frame."""

    samples, raw_ts = ring.snapshot()
    if samples.size > 0:
        max_n = max(int(window_s * metadata.sample_rate_hz), 1)
        if samples.shape[0] > max_n:
            samples = samples[-max_n:]
            raw_ts = raw_ts[-max_n:]

    stats_ts = raw_ts.copy()

    if samples.shape[0] > max_points:
        indices = np.linspace(0, samples.shape[0] - 1, max_points, dtype=int)
        samples = samples[indices]
        raw_ts = raw_ts[indices] if raw_ts.size else raw_ts

    t_rel = synthetic_relative_time(samples.shape[0], metadata.sample_rate_hz)
    frame_samples = samples.shape[0]

    return {
        "metadata": {
            "stream_name": metadata.stream_name,
            "channel_labels": list(metadata.channel_labels),
            "sample_rate_hz": metadata.sample_rate_hz,
            "source_mode": metadata.source_mode,
            "connection_status": metadata.connection_status,
            "message": metadata.message,
        },
        "samples": {
            "t_rel": _finite_list(t_rel),
            "channels": [_finite_list(samples[:, i]) for i in range(samples.shape[1])]
            if samples.ndim == 2 and frame_samples > 0
            else [],
        },
        "stats": {
            "buffer_samples": int(ring.total_written),
            "frame_samples": int(frame_samples),
            "effective_rate_hz": effective_rate_hz(stats_ts),
            "latest_sample_age_ms": latest_sample_age_ms(stats_ts) if stats_ts.size else None,
            "window_s": float(window_s),
        },
        "quality": quality_flags(samples, metadata.channel_labels),
    }


def status_frame(metadata: FrameMetadata, window_s: float = 5.0) -> dict:
    """Build an empty frame for degraded/startup states."""

    empty = RingBuffer(capacity=1, n_channels=len(metadata.channel_labels))
    return build_eeg_frame(empty, metadata=metadata, window_s=window_s)


def _finite_list(values: np.ndarray) -> list[float | None]:
    out: list[float | None] = []
    for value in np.asarray(values, dtype=float).tolist():
        out.append(float(value) if math.isfinite(float(value)) else None)
    return out
