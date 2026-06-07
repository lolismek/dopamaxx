from __future__ import annotations

import contextlib
import time
import uuid

import pytest

from acquisition.simulator import SineWaveSimulator


def test_simulator_publishes_resolvable_dsi24_stream() -> None:
    pylsl = pytest.importorskip("pylsl")
    stream_name = f"DSI24-EEG-Test-{uuid.uuid4()}"
    sim = SineWaveSimulator(stream_name=stream_name)
    try:
        sim.start()
        streams = pylsl.resolve_byprop("name", stream_name, timeout=2.0)
        assert streams, f"{stream_name} stream did not resolve within 2s"
        info = streams[0]
        assert info.channel_count() == 19
        assert info.type() == "EEG"

        inlet = pylsl.StreamInlet(info, max_buflen=2)
        sample = None
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and sample is None:
            sample, _ts = inlet.pull_sample(timeout=0.2)
        assert sample is not None
        assert len(sample) == 19
    finally:
        with contextlib.suppress(Exception):
            sim.stop()
        time.sleep(0.2)
