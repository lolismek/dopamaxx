from __future__ import annotations

import numpy as np

from acquisition.frames import FrameMetadata, build_eeg_frame
from acquisition.ring_buffer import RingBuffer
from acquisition.timebase import effective_rate_hz, synthetic_relative_time


def test_ring_buffer_preserves_order_after_wraparound() -> None:
    ring = RingBuffer(capacity=5, n_channels=2)
    ring.write(np.array([[0, 10], [1, 11], [2, 12]], dtype=float), np.array([0, 1, 2]))
    ring.write(np.array([[3, 13], [4, 14], [5, 15], [6, 16]], dtype=float), np.array([3, 4, 5, 6]))

    samples, timestamps = ring.snapshot()

    assert samples.tolist() == [[2, 12], [3, 13], [4, 14], [5, 15], [6, 16]]
    assert timestamps.tolist() == [2, 3, 4, 5, 6]


def test_synthetic_relative_time_is_uniform_at_nominal_rate() -> None:
    t = synthetic_relative_time(5, 300.0)

    assert np.allclose(t, np.array([-4 / 300, -3 / 300, -2 / 300, -1 / 300, 0]))
    assert np.allclose(np.diff(t), np.full(4, 1 / 300))


def test_chunked_duplicate_raw_timestamps_do_not_drive_frame_timebase() -> None:
    ring = RingBuffer(capacity=24, n_channels=1)
    samples = np.arange(24, dtype=float).reshape(24, 1)
    raw_ts = np.repeat(np.arange(3, dtype=float) * (8.0 / 300.0), 8)
    ring.write(samples, raw_ts)

    frame = build_eeg_frame(
        ring,
        metadata=FrameMetadata(channel_labels=("Fz",), sample_rate_hz=300.0),
        window_s=1.0,
        max_points=100,
    )
    t_rel = np.asarray(frame["samples"]["t_rel"], dtype=float)

    assert np.allclose(np.diff(t_rel), np.full(23, 1 / 300))
    assert effective_rate_hz(raw_ts) < 1000.0


def test_frame_stats_use_full_window_not_downsampled_plot_points() -> None:
    ring = RingBuffer(capacity=1200, n_channels=1)
    samples = np.arange(1200, dtype=float).reshape(1200, 1)
    raw_ts = np.arange(1200, dtype=float) / 300.0
    ring.write(samples, raw_ts)

    frame = build_eeg_frame(
        ring,
        metadata=FrameMetadata(channel_labels=("Fz",), sample_rate_hz=300.0),
        window_s=4.0,
        max_points=100,
    )

    assert frame["stats"]["frame_samples"] == 100
    assert 299.0 < frame["stats"]["effective_rate_hz"] < 301.0
