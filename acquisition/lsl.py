"""LSL stream resolution, health checks, and reader thread."""

from __future__ import annotations

import contextlib
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from acquisition.ring_buffer import RingBuffer
from acquisition.spec import CHANNEL_LABELS, HEALTH_DEFAULTS, SAMPLE_RATE_HZ, STREAM_NAME, HealthDefaults


class LSLUnavailableError(RuntimeError):
    """Raised when pylsl is not installed in the current environment."""


class StreamHealthError(RuntimeError):
    """Raised when an LSL stream resolves but does not pass the health check."""


@dataclass(frozen=True)
class ResolvedInlet:
    info: Any
    inlet: Any
    channel_labels: tuple[str, ...]
    sample_rate_hz: float
    selected_indices: tuple[int, ...] | None = None


def _pylsl() -> Any:
    try:
        import pylsl
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise LSLUnavailableError("pylsl is not installed; cannot use LSL acquisition") from exc
    return pylsl


def read_channel_labels(info: Any) -> tuple[str, ...]:
    """Read labels from LSL StreamInfo XML, falling back to chN labels."""

    n_channels = int(info.channel_count())
    labels: list[str] = []
    try:
        ch = info.desc().child("channels").child("channel")
        for _ in range(n_channels):
            label = ch.child_value("label")
            labels.append(label if label else f"ch{len(labels) + 1}")
            ch = ch.next_sibling()
    except Exception:
        labels = [f"ch{i + 1}" for i in range(n_channels)]
    return tuple(labels)


def resolve_inlet_by_name(stream_name: str = STREAM_NAME, timeout_s: float = 2.0) -> ResolvedInlet | None:
    """Resolve one LSL stream by name and return a StreamInlet."""

    pylsl = _pylsl()
    streams = pylsl.resolve_byprop("name", stream_name, timeout=timeout_s)
    if not streams:
        return None
    info = streams[0]
    inlet = pylsl.StreamInlet(info, max_buflen=60)
    labels = read_channel_labels(inlet.info())
    sample_rate = float(inlet.info().nominal_srate()) or SAMPLE_RATE_HZ
    selected_indices = scalp_channel_indices(labels)
    if selected_indices is not None:
        labels = CHANNEL_LABELS
    return ResolvedInlet(
        info=info,
        inlet=inlet,
        channel_labels=labels,
        sample_rate_hz=sample_rate,
        selected_indices=selected_indices,
    )


def scalp_channel_indices(labels: tuple[str, ...]) -> tuple[int, ...] | None:
    """Return indices that map a vendor stream to canonical 19-channel scalp order."""

    label_to_index = {label: idx for idx, label in enumerate(labels)}
    if all(label in label_to_index for label in CHANNEL_LABELS):
        return tuple(label_to_index[label] for label in CHANNEL_LABELS)
    return None


def wait_for_stream_inlet(
    stream_name: str = STREAM_NAME,
    timeout_s: float = HEALTH_DEFAULTS.launch_timeout_s,
    poll_interval_s: float = 0.25,
) -> ResolvedInlet | None:
    """Poll LSL until the stream appears or the deadline elapses."""

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        inlet = resolve_inlet_by_name(stream_name, timeout_s=poll_interval_s)
        if inlet is not None:
            return inlet
    return None


def health_check_inlet(resolved: ResolvedInlet, health: HealthDefaults = HEALTH_DEFAULTS) -> None:
    """Validate that a resolved inlet produces enough samples at the expected rate."""

    inlet = resolved.inlet
    while inlet.pull_sample(timeout=0.0)[0] is not None:
        pass

    if health.settle_s > 0:
        deadline = time.monotonic() + health.settle_s
        while time.monotonic() < deadline:
            inlet.pull_sample(timeout=0.05)
        while inlet.pull_sample(timeout=0.0)[0] is not None:
            pass

    observed = 0
    deadline = time.monotonic() + health.window_s
    while time.monotonic() < deadline:
        sample, _ts = inlet.pull_sample(timeout=0.05)
        if sample is not None:
            observed += 1

    if observed < health.min_samples:
        raise StreamHealthError(
            f"health check failed: observed {observed} samples, need >= "
            f"{health.min_samples} in {health.window_s:.2f}s"
        )

    observed_rate = observed / health.window_s if health.window_s > 0 else 0.0
    if observed_rate < health.min_rate_hz:
        raise StreamHealthError(
            f"health check failed: observed rate {observed_rate:.1f} Hz "
            f"< min_rate_hz {health.min_rate_hz:.1f}"
        )


class LSLReader:
    """Background reader that drains LSL chunks into a ring buffer."""

    def __init__(
        self,
        stream_name: str = STREAM_NAME,
        window_s: float = 5.0,
        expected_channels: int = len(CHANNEL_LABELS),
    ) -> None:
        self.stream_name = stream_name
        self.window_s = float(window_s)
        self.expected_channels = int(expected_channels)
        self.sample_rate_hz = SAMPLE_RATE_HZ
        self.channel_labels: tuple[str, ...] = CHANNEL_LABELS
        self.ring = RingBuffer(capacity=max(int(window_s * SAMPLE_RATE_HZ * 1.5), 256), n_channels=expected_channels)
        self._inlet: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, resolved: ResolvedInlet | None = None, resolve_timeout_s: float = 10.0) -> None:
        """Resolve the stream if needed and start reading chunks."""

        if self.is_running:
            return

        if resolved is None:
            resolved = wait_for_stream_inlet(self.stream_name, timeout_s=resolve_timeout_s)
        if resolved is None:
            raise TimeoutError(f"stream {self.stream_name!r} did not resolve")

        n_channels = len(resolved.channel_labels)
        self.sample_rate_hz = float(resolved.sample_rate_hz) or SAMPLE_RATE_HZ
        self.channel_labels = tuple(resolved.channel_labels)
        selected_indices = resolved.selected_indices
        self.ring = RingBuffer(
            capacity=max(int(self.window_s * self.sample_rate_hz * 1.5), 256),
            n_channels=n_channels,
        )
        self._inlet = resolved.inlet
        self._last_error = None
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._read_loop,
            args=(selected_indices,),
            name="dsi24-lsl-reader",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._inlet is not None:
            with contextlib.suppress(Exception):
                self._inlet.close_stream()
        self._thread = None
        self._inlet = None

    def _read_loop(self, selected_indices: tuple[int, ...] | None) -> None:
        while not self._stop.is_set():
            try:
                chunk, timestamps = self._inlet.pull_chunk(timeout=0.25, max_samples=512)
            except Exception as exc:
                self._last_error = f"LSL read failed: {exc}"
                return
            if not chunk:
                continue
            samples = np.asarray(chunk, dtype=float)
            ts = np.asarray(timestamps, dtype=float)
            if samples.ndim != 2 or ts.ndim != 1 or samples.shape[0] != ts.shape[0]:
                self._last_error = "LSL returned malformed sample chunk"
                continue
            if selected_indices is not None:
                samples = samples[:, selected_indices]
            self.ring.write(samples, ts)
