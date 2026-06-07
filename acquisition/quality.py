"""Lightweight signal quality flags for live frames."""

from __future__ import annotations

import numpy as np

FLAT_STD_THRESHOLD = 1e-9
CLIP_DEVIATION_THRESHOLD = 750.0


def quality_flags(
    samples: np.ndarray,
    channel_labels: tuple[str, ...],
    flat_std_threshold: float = FLAT_STD_THRESHOLD,
    clip_deviation_threshold: float = CLIP_DEVIATION_THRESHOLD,
) -> dict:
    """Return flat-channel and clipping flags for a sample window."""

    data = np.asarray(samples, dtype=float)
    if data.size == 0:
        return {
            "flat_channels": [],
            "clip_channels": [],
            "flat_channel_labels": [],
            "clip_channel_labels": [],
            "flat_std_threshold": flat_std_threshold,
            "clip_deviation_threshold": clip_deviation_threshold,
        }

    std = np.nanstd(data, axis=0)
    centered = data - np.nanmean(data, axis=0, keepdims=True)
    max_abs = np.nanmax(np.abs(centered), axis=0)
    flat = [bool(x <= flat_std_threshold) for x in std]
    clip = [bool(x >= clip_deviation_threshold) for x in max_abs]
    labels = list(channel_labels)
    return {
        "flat_channels": flat,
        "clip_channels": clip,
        "flat_channel_labels": [label for label, flag in zip(labels, flat, strict=False) if flag],
        "clip_channel_labels": [label for label, flag in zip(labels, clip, strict=False) if flag],
        "flat_std_threshold": flat_std_threshold,
        "clip_deviation_threshold": clip_deviation_threshold,
    }
