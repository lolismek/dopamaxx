from __future__ import annotations

from acquisition.service import AcquisitionRuntime, RuntimeConfig


class _FakeSimulator:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


def test_health_reports_degraded_when_stream_does_not_resolve(monkeypatch) -> None:
    monkeypatch.setattr("acquisition.service.SineWaveSimulator", lambda stream_name: _FakeSimulator())
    monkeypatch.setattr("acquisition.service.wait_for_stream_inlet", lambda *args, **kwargs: None)

    runtime = AcquisitionRuntime(
        RuntimeConfig(simulate=True, stream_name="Missing-DSI24", launch_timeout_s=0.01)
    )

    runtime.start()
    health = runtime.health()

    assert health["status"] == "degraded"
    assert "did not appear" in health["message"]
