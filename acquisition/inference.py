"""Lightweight live EEG heuristics for DopaMAXX MVP inference."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

THETA_BAND = (4.0, 8.0)
ALPHA_BAND = (8.0, 13.0)
BETA_BAND = (13.0, 30.0)
TOTAL_BAND = (4.0, 30.0)
MIN_INFERENCE_S = 1.5
EPS = 1e-9

FOCUS_CHANNELS = ("F3", "Fz", "F4", "C3", "Cz", "C4")
FRONTAL_CHANNELS = ("Fp1", "Fp2", "F7", "F3", "Fz", "F4", "F8")
LEFT_FRONTAL = ("Fp1", "F7", "F3")
RIGHT_FRONTAL = ("Fp2", "F8", "F4")


@dataclass(frozen=True)
class BandSummary:
    theta: float
    alpha: float
    beta: float


def infer_live_state(
    samples: np.ndarray,
    channel_labels: tuple[str, ...],
    sample_rate_hz: float,
) -> dict:
    """Infer focus/reward heuristics from a recent EEG window.

    The implementation intentionally uses explainable band-power transforms
    rather than a trained model. Scores are not diagnostic or scientifically
    validated; they are MVP control signals for live demo behavior.
    """

    data = np.asarray(samples, dtype=float)
    if data.ndim != 2 or data.shape[0] < int(MIN_INFERENCE_S * sample_rate_hz):
        return _empty_inference("insufficient_data")

    labels = tuple(channel_labels)
    clean = _clean_window(data)
    if clean.size == 0:
        return _empty_inference("bad_signal")

    theta = _band_power(clean, sample_rate_hz, THETA_BAND)
    alpha = _band_power(clean, sample_rate_hz, ALPHA_BAND)
    beta = _band_power(clean, sample_rate_hz, BETA_BAND)
    total = _band_power(clean, sample_rate_hz, TOTAL_BAND)

    rel_theta = theta / (total + EPS)
    rel_alpha = alpha / (total + EPS)
    rel_beta = beta / (total + EPS)

    focus_idx = _indices(labels, FOCUS_CHANNELS)
    frontal_idx = _indices(labels, FRONTAL_CHANNELS)
    left_idx = _indices(labels, LEFT_FRONTAL)
    right_idx = _indices(labels, RIGHT_FRONTAL)

    if not focus_idx:
        return _empty_inference("missing_focus_channels")

    focus_theta = float(np.nanmean(rel_theta[focus_idx]))
    focus_alpha = float(np.nanmean(rel_alpha[focus_idx]))
    focus_beta = float(np.nanmean(rel_beta[focus_idx]))
    engagement_index = focus_beta / (focus_alpha + focus_theta + EPS)

    frontal_alpha = float(np.nanmean(rel_alpha[frontal_idx])) if frontal_idx else focus_alpha
    focus_score = _score_focus(engagement_index, frontal_alpha)

    reward_score = 0.0
    faa = 0.0
    if left_idx and right_idx:
        # Alpha is inversely related to cortical activation. Less left alpha
        # than right alpha is used here as a positive approach/reward proxy.
        left_alpha = float(np.nanmean(alpha[left_idx]))
        right_alpha = float(np.nanmean(alpha[right_idx]))
        faa = math.log((right_alpha + EPS) / (left_alpha + EPS))
        reward_score = float(np.clip(faa / 1.25, -1.0, 1.0))

    dominant_band = _dominant_band(
        BandSummary(theta=focus_theta, alpha=focus_alpha, beta=focus_beta)
    )
    mood = _focus_mood(focus_score, frontal_alpha, reward_score)

    return {
        "status": "ok",
        "focus_score": round(float(focus_score), 4),
        "focus_mood": mood,
        "reward_score": round(float(reward_score), 4),
        "reward_mood": _reward_mood(reward_score),
        "dominant_band": dominant_band,
        "features": {
            "engagement_index": round(float(engagement_index), 4),
            "frontal_alpha": round(float(frontal_alpha), 4),
            "frontal_alpha_asymmetry": round(float(faa), 4),
            "relative_theta": round(float(focus_theta), 4),
            "relative_alpha": round(float(focus_alpha), 4),
            "relative_beta": round(float(focus_beta), 4),
        },
        "bands": {
            "theta_hz": list(THETA_BAND),
            "alpha_hz": list(ALPHA_BAND),
            "beta_hz": list(BETA_BAND),
        },
    }


def _clean_window(data: np.ndarray) -> np.ndarray:
    clean = data.astype(float, copy=True)
    if np.isnan(clean).any():
        means = np.nanmean(clean, axis=0)
        means = np.where(np.isfinite(means), means, 0.0)
        inds = np.where(~np.isfinite(clean))
        clean[inds] = np.take(means, inds[1])
    clean -= np.mean(clean, axis=0, keepdims=True)
    return clean


def _band_power(data: np.ndarray, sample_rate_hz: float, band: tuple[float, float]) -> np.ndarray:
    n = data.shape[0]
    if n < 2:
        return np.zeros(data.shape[1], dtype=float)
    window = np.hanning(n).reshape(-1, 1)
    tapered = data * window
    spectrum = np.fft.rfft(tapered, axis=0)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate_hz)
    mask = (freqs >= band[0]) & (freqs < band[1])
    if not np.any(mask):
        return np.zeros(data.shape[1], dtype=float)
    power = np.abs(spectrum[mask]) ** 2
    return np.nanmean(power, axis=0)


def _score_focus(engagement_index: float, frontal_alpha: float) -> float:
    engagement_component = _sigmoid((math.log(engagement_index + EPS) + 0.25) * 2.1)
    alpha_penalty = _sigmoid((frontal_alpha - 0.42) * 8.0)
    return float(np.clip(0.82 * engagement_component + 0.18 * (1.0 - alpha_penalty), 0.0, 1.0))


def _focus_mood(focus_score: float, frontal_alpha: float, reward_score: float) -> str:
    if focus_score >= 0.7:
        return "locked_in"
    if focus_score <= 0.36 and frontal_alpha >= 0.34:
        return "drifting"
    if reward_score >= 0.45:
        return "reward_hit"
    if reward_score <= -0.45:
        return "reward_miss"
    return "steady"


def _reward_mood(reward_score: float) -> str:
    if reward_score >= 0.45:
        return "hit"
    if reward_score <= -0.45:
        return "miss"
    return "neutral"


def _dominant_band(summary: BandSummary) -> str:
    values = {
        "theta": summary.theta,
        "alpha": summary.alpha,
        "beta": summary.beta,
    }
    return max(values, key=values.get)


def _indices(labels: tuple[str, ...], names: tuple[str, ...]) -> list[int]:
    lookup = {label: i for i, label in enumerate(labels)}
    return [lookup[name] for name in names if name in lookup]


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _empty_inference(status: str) -> dict:
    return {
        "status": status,
        "focus_score": None,
        "focus_mood": "unknown",
        "reward_score": None,
        "reward_mood": "unknown",
        "dominant_band": "unknown",
        "features": {},
        "bands": {
            "theta_hz": list(THETA_BAND),
            "alpha_hz": list(ALPHA_BAND),
            "beta_hz": list(BETA_BAND),
        },
    }
