from __future__ import annotations

import uuid

import pytest


def test_websocket_emits_metadata_and_sample_frames_from_simulator() -> None:
    pytest.importorskip("pylsl")
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from acquisition.service import AcquisitionRuntime, RuntimeConfig, create_app

    stream_name = f"DSI24-EEG-Test-{uuid.uuid4()}"
    runtime = AcquisitionRuntime(
        RuntimeConfig(simulate=True, stream_name=stream_name, launch_timeout_s=2.0)
    )
    app = create_app(runtime)

    with TestClient(app) as client:
        health = client.get("/health").json()
        assert health["status"] == "connected"
        with client.websocket_connect("/stream/eeg") as websocket:
            frame = websocket.receive_json()
            for _ in range(10):
                if frame["samples"]["channels"]:
                    break
                frame = websocket.receive_json()

    assert frame["metadata"]["stream_name"] == stream_name
    assert frame["metadata"]["source_mode"] == "simulator"
    assert frame["metadata"]["connection_status"] == "connected"
    assert frame["samples"]["channels"]
