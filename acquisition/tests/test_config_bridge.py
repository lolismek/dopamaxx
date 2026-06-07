from __future__ import annotations

import io
from pathlib import Path

import pytest

from acquisition.bridge import BridgeProcess, bridge_power_cycle_hint, build_bridge_command
from acquisition.config import (
    DOPAMAXX_DSI_BRIDGE_ENV,
    RLHB_DSI_BRIDGE_ENV,
    BridgeConfigError,
    resolve_bridge_path,
)


def test_resolve_bridge_path_prefers_dopamaxx_env(monkeypatch, tmp_path: Path) -> None:
    dopamaxx_path = tmp_path / "dsi2lsl.exe"
    rlhb_path = tmp_path / "rlhb-dsi2lsl.exe"
    monkeypatch.setenv(DOPAMAXX_DSI_BRIDGE_ENV, str(dopamaxx_path))
    monkeypatch.setenv(RLHB_DSI_BRIDGE_ENV, str(rlhb_path))

    assert resolve_bridge_path() == dopamaxx_path


def test_resolve_bridge_path_falls_back_to_rlhb_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(DOPAMAXX_DSI_BRIDGE_ENV, raising=False)
    rlhb_path = tmp_path / "dsi2lsl.exe"
    monkeypatch.setenv(RLHB_DSI_BRIDGE_ENV, str(rlhb_path))

    assert resolve_bridge_path() == rlhb_path


def test_resolve_bridge_path_rejects_non_absolute(monkeypatch) -> None:
    monkeypatch.delenv(DOPAMAXX_DSI_BRIDGE_ENV, raising=False)
    monkeypatch.delenv(RLHB_DSI_BRIDGE_ENV, raising=False)

    with pytest.raises(BridgeConfigError, match="absolute"):
        resolve_bridge_path("dsi2lsl.exe")


def test_bridge_command_includes_path_port_and_stream_name(tmp_path: Path) -> None:
    bridge_path = tmp_path / "dsi2lsl.exe"

    command = build_bridge_command(bridge_path, "COM3", "DSI24-EEG")

    assert command.argv == [
        str(bridge_path),
        "--port=COM3",
        "--lsl-stream-name=DSI24-EEG",
    ]
    assert command.cwd == bridge_path.resolve().parent


def test_bridge_process_sets_cwd_to_exe_directory(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class FakeProc:
        stdout = io.StringIO("")
        stderr = io.StringIO("")

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeProc()

    monkeypatch.setattr("acquisition.bridge.subprocess.Popen", fake_popen)
    bridge_path = tmp_path / "bin" / "dsi2lsl.exe"
    command = build_bridge_command(bridge_path, "COM3")
    process = BridgeProcess(command)

    process.start()
    process.stop()

    assert calls
    _args, kwargs = calls[0]
    assert kwargs["cwd"] == str(bridge_path.resolve().parent)


def test_power_cycle_hint_detects_common_headset_off_signature() -> None:
    output = """
    DSI Message: Connected to COM3
    DSI Message: No reply received - resending command: Master.DataAcquisitionMode
    Command failed too many times.
    """

    assert bridge_power_cycle_hint(output) is not None
