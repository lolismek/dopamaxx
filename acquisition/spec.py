"""DSI-24 stream constants and health defaults."""

from __future__ import annotations

from dataclasses import dataclass

STREAM_NAME = "DSI24-EEG"
STREAM_TYPE = "EEG"
SAMPLE_RATE_HZ = 300.0

CHANNEL_LABELS: tuple[str, ...] = (
    "Fp1",
    "Fp2",
    "F7",
    "F3",
    "Fz",
    "F4",
    "F8",
    "T3",
    "C3",
    "Cz",
    "C4",
    "T4",
    "T5",
    "P3",
    "Pz",
    "P4",
    "T6",
    "O1",
    "O2",
)

CHANNEL_INDEX: dict[str, int] = {label: i for i, label in enumerate(CHANNEL_LABELS)}


@dataclass(frozen=True)
class HealthDefaults:
    """Post-launch validation defaults for the real DSI-24 bridge."""

    launch_timeout_s: float = 60.0
    settle_s: float = 3.0
    window_s: float = 2.0
    min_samples: int = 300
    min_rate_hz: float = 290.0


HEALTH_DEFAULTS = HealthDefaults()
