"""Synthetic DSI-24 LSL publisher with demo-state injection."""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass

from acquisition.spec import CHANNEL_INDEX, CHANNEL_LABELS, SAMPLE_RATE_HZ, STREAM_NAME, STREAM_TYPE

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Injection:
    freq_hz: float
    amplitude: float


class SineWaveSimulator:
    """Publishes a DSI-24-shaped sine-wave LSL stream."""

    def __init__(self, stream_name: str = STREAM_NAME) -> None:
        self.stream_name = stream_name
        self._outlet = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._inject_lock = threading.Lock()
        self._injection: dict[int, Injection] = {}

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        pylsl = _pylsl()
        info = pylsl.StreamInfo(
            name=self.stream_name,
            type=STREAM_TYPE,
            channel_count=len(CHANNEL_LABELS),
            nominal_srate=SAMPLE_RATE_HZ,
            channel_format=pylsl.cf_float32,
            source_id=f"dopamaxx-sim-{self.stream_name}",
        )
        channels = info.desc().append_child("channels")
        for label in CHANNEL_LABELS:
            ch = channels.append_child("channel")
            ch.append_child_value("label", label)
            ch.append_child_value("type", STREAM_TYPE)
        self._outlet = pylsl.StreamOutlet(info, chunk_size=0, max_buffered=60)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_safely, name="dsi24-simulator", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._outlet = None
        self.clear_injection()

    def inject_sinusoid(
        self,
        freq_hz: float,
        channel_indices: Sequence[int],
        amplitude: float = 50.0,
        duration_s: float | None = None,
    ) -> None:
        pattern = {int(idx): Injection(freq_hz=float(freq_hz), amplitude=float(amplitude)) for idx in channel_indices}
        self.inject_pattern(pattern, duration_s=duration_s)

    def inject_pattern(
        self,
        pattern: dict[int, Injection],
        duration_s: float | None = None,
    ) -> None:
        with self._inject_lock:
            self._injection = {
                int(idx): injection
                for idx, injection in pattern.items()
                if 0 <= int(idx) < len(CHANNEL_LABELS)
            }
        if duration_s is not None:
            timer = threading.Timer(float(duration_s), self.clear_injection)
            timer.daemon = True
            timer.start()

    def inject_state(self, state: str, duration_s: float = 5.0) -> str:
        """Inject a named demo state and return the normalized state name."""

        normalized = state.strip().lower().replace("_", " ").replace("-", " ")
        if normalized == "neutral":
            self.clear_injection()
            return "Neutral"
        if normalized == "focused":
            self.inject_sinusoid(
                freq_hz=18.0,
                channel_indices=_indices("F3", "Fz", "F4", "Cz"),
                amplitude=45.0,
                duration_s=duration_s,
            )
            return "Focused"
        if normalized == "drifting":
            self.inject_sinusoid(
                freq_hz=10.0,
                channel_indices=_indices("Fp1", "Fp2", "F3", "Fz", "F4"),
                amplitude=65.0,
                duration_s=duration_s,
            )
            return "Drifting"
        if normalized == "reward hit":
            self.inject_pattern(
                {
                    CHANNEL_INDEX["Fp1"]: Injection(20.0, 70.0),
                    CHANNEL_INDEX["F3"]: Injection(20.0, 70.0),
                    CHANNEL_INDEX["Fz"]: Injection(14.0, 45.0),
                },
                duration_s=duration_s,
            )
            return "Reward Hit"
        if normalized == "reward miss":
            self.inject_pattern(
                {
                    CHANNEL_INDEX["Fp2"]: Injection(10.0, 70.0),
                    CHANNEL_INDEX["F4"]: Injection(10.0, 70.0),
                    CHANNEL_INDEX["Fz"]: Injection(6.0, 40.0),
                },
                duration_s=duration_s,
            )
            return "Reward Miss"
        raise ValueError(f"unknown simulator state {state!r}")

    def clear_injection(self) -> None:
        with self._inject_lock:
            self._injection.clear()

    def _run_safely(self) -> None:
        try:
            self._run()
        except Exception:
            _LOG.exception("DSI-24 simulator crashed")

    def _run(self) -> None:
        outlet = self._outlet
        if outlet is None:
            return
        n_channels = len(CHANNEL_LABELS)
        period_s = 1.0 / SAMPLE_RATE_HZ
        phases = [2.0 * math.pi * i / n_channels for i in range(n_channels)]
        start_t = time.monotonic()
        next_tick = start_t
        while not self._stop.is_set():
            now = time.monotonic()
            due = max(1, min(int((now - next_tick) / period_s) + 1, 256))
            with self._inject_lock:
                injection = dict(self._injection)
            for _ in range(due):
                t = next_tick - start_t
                sample: list[float] = []
                for idx in range(n_channels):
                    injected = injection.get(idx)
                    if injected is not None:
                        sample.append(
                            injected.amplitude * math.sin(2.0 * math.pi * injected.freq_hz * t)
                        )
                    else:
                        sample.append(math.sin(2.0 * math.pi * t + phases[idx]))
                outlet.push_sample(sample)
                next_tick += period_s
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                if self._stop.wait(timeout=sleep_for):
                    break


def _indices(*labels: str) -> list[int]:
    return [CHANNEL_INDEX[label] for label in labels]


def _pylsl():
    try:
        import pylsl
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise RuntimeError("pylsl is not installed; cannot start the DSI-24 simulator") from exc
    return pylsl
