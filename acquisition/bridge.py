"""Launcher for the Wearable Sensing dsi2lsl bridge."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from acquisition.config import BridgeConfigError
from acquisition.spec import STREAM_NAME

_MAX_OUTPUT_LINES = 200
_POWER_CYCLE_MARKERS = (
    "Master.DataAcquisitionMode",
    "Command failed too many times",
)


@dataclass(frozen=True)
class BridgeCommand:
    argv: list[str]
    cwd: Path


def build_bridge_command(
    bridge_path: str | Path,
    port: str,
    stream_name: str = STREAM_NAME,
) -> BridgeCommand:
    """Render the external dsi2lsl command and cwd."""

    path = Path(bridge_path).expanduser()
    if not path.is_absolute():
        raise BridgeConfigError(
            "dsi2lsl.exe path must be absolute so its co-located DLLs load reliably"
        )
    if not port.strip():
        raise BridgeConfigError("real DSI-24 mode requires an explicit serial/COM port")
    argv = [str(path), f"--port={port.strip()}", f"--lsl-stream-name={stream_name}"]
    return BridgeCommand(argv=argv, cwd=path.resolve().parent)


def bridge_power_cycle_hint(output: str) -> str | None:
    """Return an operator hint when bridge output matches the common DSI failure."""

    if all(marker in output for marker in _POWER_CYCLE_MARKERS):
        return (
            "The bridge opened the COM port but the headset did not answer. "
            "Power-cycle the DSI-24, confirm battery/pairing, and close any other "
            "app using the same COM port."
        )
    return None


class BridgeProcess:
    """Owns the external bridge subprocess and a bounded output buffer."""

    def __init__(self, command: BridgeCommand) -> None:
        self.command = command
        self._proc: subprocess.Popen[str] | None = None
        self._lines: deque[str] = deque(maxlen=_MAX_OUTPUT_LINES)
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def returncode(self) -> int | None:
        return None if self._proc is None else self._proc.poll()

    def start(self) -> None:
        """Launch dsi2lsl and start background output readers."""

        if self._proc is not None:
            return

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        self._proc = subprocess.Popen(
            self.command.argv,
            cwd=str(self.command.cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        for name, stream in (("stdout", self._proc.stdout), ("stderr", self._proc.stderr)):
            if stream is None:
                continue
            thread = threading.Thread(
                target=self._read_stream,
                args=(name, stream),
                name=f"dsi2lsl-{name}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()

    def output_snapshot(self) -> str:
        with self._lock:
            return "\n".join(self._lines)

    def operator_hint(self) -> str | None:
        return bridge_power_cycle_hint(self.output_snapshot())

    def stop(self, timeout_s: float = 5.0) -> None:
        """Terminate the bridge. Safe to call repeatedly."""

        proc = self._proc
        if proc is None:
            return

        if proc.poll() is None:
            with contextlib.suppress(OSError):
                if os.name == "nt":
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    proc.terminate()
            try:
                proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError):
                    proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=timeout_s)

        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=0.25)
        self._threads.clear()
        self._proc = None

    def _read_stream(self, name: str, stream: TextIO) -> None:
        try:
            for line in stream:
                text = line.rstrip()
                if not text:
                    continue
                with self._lock:
                    self._lines.append(f"{name}: {text}")
        finally:
            with contextlib.suppress(Exception):
                stream.close()
