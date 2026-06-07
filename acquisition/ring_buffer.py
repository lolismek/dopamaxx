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
