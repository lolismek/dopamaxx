"""Thread-safe rolling sample buffer."""

from __future__ import annotations

import threading

import numpy as np


class RingBuffer:
    """Single-producer/single-consumer ring buffer for EEG samples."""

    def __init__(self, capacity: int, n_channels: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if n_channels <= 0:
            raise ValueError("n_channels must be > 0")
        self._capacity = int(capacity)
        self._samples = np.zeros((self._capacity, n_channels), dtype=float)
        self._timestamps = np.zeros(self._capacity, dtype=float)
        self._write = 0
        self._filled = 0
        self._total_written = 0
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def total_written(self) -> int:
        with self._lock:
            return self._total_written

    def write(self, samples: np.ndarray, timestamps: np.ndarray) -> None:
        samples = np.asarray(samples, dtype=float)
        timestamps = np.asarray(timestamps, dtype=float)
        if samples.ndim != 2:
            raise ValueError("samples must be a 2D array shaped (n_samples, n_channels)")
        if timestamps.ndim != 1 or timestamps.shape[0] != samples.shape[0]:
            raise ValueError("timestamps must be a 1D array matching samples rows")
        k = samples.shape[0]
        if k == 0:
            return

        with self._lock:
            if k >= self._capacity:
                self._samples[:] = samples[-self._capacity :]
                self._timestamps[:] = timestamps[-self._capacity :]
                self._write = 0
                self._filled = self._capacity
                self._total_written += k
                return

            end = self._write + k
            if end <= self._capacity:
                self._samples[self._write : end] = samples
                self._timestamps[self._write : end] = timestamps
            else:
                split = self._capacity - self._write
                self._samples[self._write :] = samples[:split]
                self._timestamps[self._write :] = timestamps[:split]
                self._samples[: k - split] = samples[split:]
                self._timestamps[: k - split] = timestamps[split:]

            self._write = (self._write + k) % self._capacity
            self._filled = min(self._capacity, self._filled + k)
            self._total_written += k

    def snapshot(self) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            n = self._filled
            if n == 0:
                return (
                    np.empty((0, self._samples.shape[1]), dtype=float),
                    np.empty((0,), dtype=float),
                )
            if n < self._capacity:
                return self._samples[:n].copy(), self._timestamps[:n].copy()
            idx = self._write
            return (
                np.concatenate([self._samples[idx:], self._samples[:idx]]),
                np.concatenate([self._timestamps[idx:], self._timestamps[:idx]]),
            )

    def read_since(
        self,
        last_sequence: int,
        max_samples: int | None = None,
    ) -> tuple[np.ndarray, np.ndarray, int, int, bool]:
        """Return samples written after ``last_sequence``.

        Sequence numbers are monotonically increasing sample counts. The
        returned tuple is ``(samples, timestamps, first_sequence,
        next_sequence, dropped)`` where ``next_sequence`` is the value the
        caller should pass on the next read. If the caller falls behind the
        ring buffer, old samples are skipped and ``dropped`` is true.
        """

        with self._lock:
            current = self._total_written
            oldest = current - self._filled
            start = max(int(last_sequence), oldest)
            dropped = int(last_sequence) < oldest
            if max_samples is not None and max_samples > 0 and current - start > max_samples:
                start = current - int(max_samples)
                dropped = True
            if start >= current or self._filled == 0:
                empty = np.empty((0, self._samples.shape[1]), dtype=float)
                return empty, np.empty((0,), dtype=float), current, current, dropped

            samples, timestamps = self._ordered_unlocked()
            offset = start - oldest
            out_samples = samples[offset:].copy()
            out_timestamps = timestamps[offset:].copy()
            return out_samples, out_timestamps, start, current, dropped

    def _ordered_unlocked(self) -> tuple[np.ndarray, np.ndarray]:
        n = self._filled
        if n == 0:
            return (
                np.empty((0, self._samples.shape[1]), dtype=float),
                np.empty((0,), dtype=float),
            )
        if n < self._capacity:
            return self._samples[:n].copy(), self._timestamps[:n].copy()
        idx = self._write
        return (
            np.concatenate([self._samples[idx:], self._samples[:idx]]),
            np.concatenate([self._timestamps[idx:], self._timestamps[:idx]]),
        )
