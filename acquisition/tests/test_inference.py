from __future__ import annotations

import numpy as np

from acquisition.inference import infer_live_state
from acquisition.spec import CHANNEL_LABELS


def _window(freq_by_label: dict[str, float], seconds: float = 4.0, rate: float = 300.0) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    data = np.zeros((t.size, len(CHANNEL_LABELS)), dtype=float)
    for i, label in enumerate(CHANNEL_LABELS):
        freq = freq_by_label.get(label, 10.0)
        data[:, i] = 50.0 * np.sin(2.0 * np.pi * freq * t)
    return data


def test_focus_score_rises_for_beta_dominant_frontal_window() -> None:
    data = _window({label: 18.0 for label in ("F3", "Fz", "F4", "C3", "Cz", "C4")})

    inference = infer_live_state(data, CHANNEL_LABELS, 300.0)

    assert inference["status"] == "ok"
    assert inference["focus_score"] > 0.65
    assert inference["dominant_band"] == "beta"


def test_focus_mood_drifts_for_alpha_dominant_frontal_window() -> None:
    data = _window({label: 10.0 for label in ("F3", "Fz", "F4", "C3", "Cz", "C4")})

    inference = infer_live_state(data, CHANNEL_LABELS, 300.0)

    assert inference["status"] == "ok"
    assert inference["focus_score"] < 0.45
    assert inference["focus_mood"] in {"drifting", "steady"}


def test_reward_score_reflects_frontal_alpha_asymmetry() -> None:
    data = _window({})
    left = [CHANNEL_LABELS.index(label) for label in ("Fp1", "F7", "F3")]
    right = [CHANNEL_LABELS.index(label) for label in ("Fp2", "F8", "F4")]
    data[:, left] *= 0.25
    data[:, right] *= 2.0

    inference = infer_live_state(data, CHANNEL_LABELS, 300.0)

    assert inference["reward_score"] > 0.4
    assert inference["reward_mood"] == "hit"


def test_inference_reports_insufficient_data_for_short_windows() -> None:
    data = np.zeros((20, len(CHANNEL_LABELS)), dtype=float)

    inference = infer_live_state(data, CHANNEL_LABELS, 300.0)

    assert inference["status"] == "insufficient_data"
    assert inference["focus_score"] is None
