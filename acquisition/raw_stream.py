"""Binary protocol helpers for high-throughput EEG streaming."""

from __future__ import annotations

import json
import struct
from typing import Any

import numpy as np

PROTOCOL = "dopamaxx.raw_eeg.v1"
HEADER_PREFIX = struct.Struct("<I")


def hello_message(metadata: dict[str, Any]) -> dict[str, Any]:
    """Return the initial JSON text message for raw EEG WebSocket clients."""

    return {
        "type": "raw_eeg_hello",
        "protocol": PROTOCOL,
        "byte_order": "little",
        "header_prefix_bytes": HEADER_PREFIX.size,
        "timestamp_dtype": "float64",
        "sample_dtype": "float32",
        "sample_layout": "row_major_samples_by_channels",
        "metadata": metadata,
    }


def encode_raw_frame(
    samples: np.ndarray,
    timestamps: np.ndarray,
    *,
    stream_name: str,
    channel_labels: tuple[str, ...],
    sample_rate_hz: float,
    first_sequence: int,
    next_sequence: int,
    dropped: bool,
) -> bytes:
    """Encode one raw EEG chunk as a compact binary WebSocket payload."""

    sample_arr = np.ascontiguousarray(samples, dtype="<f4")
    ts_arr = np.ascontiguousarray(timestamps, dtype="<f8")
    if sample_arr.ndim != 2:
        raise ValueError("samples must be shaped (n_samples, n_channels)")
    if ts_arr.ndim != 1 or ts_arr.shape[0] != sample_arr.shape[0]:
        raise ValueError("timestamps must be 1D and match sample rows")

    header = {
        "type": "raw_eeg_chunk",
        "protocol": PROTOCOL,
        "stream_name": stream_name,
        "channel_labels": list(channel_labels),
        "sample_rate_hz": float(sample_rate_hz),
        "n_samples": int(sample_arr.shape[0]),
        "n_channels": int(sample_arr.shape[1]),
        "first_sequence": int(first_sequence),
        "next_sequence": int(next_sequence),
        "dropped": bool(dropped),
        "timestamp_dtype": "float64",
        "sample_dtype": "float32",
        "sample_layout": "row_major_samples_by_channels",
    }
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    return HEADER_PREFIX.pack(len(header_bytes)) + header_bytes + ts_arr.tobytes() + sample_arr.tobytes()


def decode_raw_frame(payload: bytes) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    """Decode a raw EEG chunk. Useful for remote consumers and tests."""

    if len(payload) < HEADER_PREFIX.size:
        raise ValueError("payload too short for header prefix")
    (header_len,) = HEADER_PREFIX.unpack(payload[: HEADER_PREFIX.size])
    header_start = HEADER_PREFIX.size
    header_end = header_start + header_len
    if len(payload) < header_end:
        raise ValueError("payload too short for header")
    header = json.loads(payload[header_start:header_end].decode("utf-8"))
    n_samples = int(header["n_samples"])
    n_channels = int(header["n_channels"])

    ts_bytes = n_samples * np.dtype("<f8").itemsize
    ts_start = header_end
    ts_end = ts_start + ts_bytes
    sample_start = ts_end
    expected = sample_start + n_samples * n_channels * np.dtype("<f4").itemsize
    if len(payload) != expected:
        raise ValueError(f"payload size mismatch: expected {expected}, got {len(payload)}")

    timestamps = np.frombuffer(payload[ts_start:ts_end], dtype="<f8").copy()
    samples = np.frombuffer(payload[sample_start:], dtype="<f4").reshape(n_samples, n_channels).copy()
    return header, timestamps, samples
