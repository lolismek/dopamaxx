from __future__ import annotations

import uuid

import numpy as np
import pytest

from acquisition.raw_stream import decode_raw_frame, encode_raw_frame
from acquisition.ring_buffer import RingBuffer


def test_ring_buffer_read_since_returns_sequences_and_drops_when_lagging() -> None:
    ring = RingBuffer(capacity=5, n_channels=2)
    ring.write(np.arange(14, dtype=float).reshape(7, 2), np.arange(7, dtype=float))

    samples, ts, first, next_seq, dropped = ring.read_since(0)

    assert dropped is True
    assert first == 2
    assert next_seq == 7
    assert ts.tolist() == [2, 3, 4, 5, 6]
    assert samples.tolist() == [[4, 5], [6, 7], [8, 9], [10, 11], [12, 13]]


def test_raw_binary_frame_round_trips() -> None:
    samples = np.array([[1.0, 2.0], [3.5, 4.5]], dtype=float)
    ts = np.array([10.0, 10.003], dtype=float)

    payload = encode_raw_frame(
        samples,
        ts,
        stream_name="DSI24-EEG",
        channel_labels=("Fz", "Cz"),
        sample_rate_hz=300.0,
        first_sequence=42,
        next_sequence=44,
        dropped=False,
    )
    header, decoded_ts, decoded_samples = decode_raw_frame(payload)

    assert header["protocol"] == "dopamaxx.raw_eeg.v1"
    assert header["first_sequence"] == 42
    assert header["next_sequence"] == 44
    assert np.allclose(decoded_ts, ts)
    assert np.allclose(decoded_samples, samples)


def test_raw_websocket_stream_emits_binary_chunks() -> None:
    pytest.importorskip("pylsl")
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from acquisition.service import AcquisitionRuntime, RuntimeConfig, create_app

    stream_name = f"DSI24-EEG-Raw-{uuid.uuid4()}"
    runtime = AcquisitionRuntime(
        RuntimeConfig(simulate=True, stream_name=stream_name, launch_timeout_s=2.0)
    )
    app = create_app(runtime)

    with TestClient(app) as client:
        with client.websocket_connect("/stream/raw?max_samples=128&poll_ms=1") as websocket:
            hello = websocket.receive_json()
            assert hello["protocol"] == "dopamaxx.raw_eeg.v1"
            payload = websocket.receive_bytes()

    header, ts, samples = decode_raw_frame(payload)
    assert header["stream_name"] == stream_name
    assert samples.shape[0] > 0
    assert samples.shape[1] == 19
    assert ts.shape[0] == samples.shape[0]
