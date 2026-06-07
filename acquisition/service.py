"""FastAPI service for DSI-24 acquisition streaming."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from acquisition.bridge import BridgeProcess, build_bridge_command
from acquisition.config import BridgeConfigError, require_port, resolve_bridge_path
from acquisition.frames import FrameMetadata, build_eeg_frame, status_frame
from acquisition.lsl import LSLReader, health_check_inlet, wait_for_stream_inlet
from acquisition.simulator import SineWaveSimulator
from acquisition.spec import CHANNEL_LABELS, HEALTH_DEFAULTS, SAMPLE_RATE_HZ, STREAM_NAME


@dataclass(frozen=True)
class RuntimeConfig:
    simulate: bool = False
    port: str | None = None
    bridge_path: str | Path | None = None
    stream_name: str = STREAM_NAME
    window_s: float = 5.0
    launch_timeout_s: float | None = None


class InjectionRequest(BaseModel):
    state: str | None = Field(default=None)
    freq_hz: float | None = Field(default=None, gt=0)
    channel_indices: list[int] | None = None
    amplitude: float = 50.0
    duration_s: float | None = Field(default=5.0, gt=0)


class AcquisitionRuntime:
    """Owns producer, consumer, and current service status."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.simulator: SineWaveSimulator | None = None
        self.bridge: BridgeProcess | None = None
        self.reader: LSLReader | None = None
        self.connection_status = "stopped"
        self.message: str | None = None
        self._started = False

    @property
    def source_mode(self) -> str:
        return "simulator" if self.config.simulate else "hardware"

    def start(self) -> None:
        """Start acquisition if possible; keep service alive on failure."""

        if self._started:
            return
        self._started = True
        self.connection_status = "starting"
        self.message = None

        try:
            if self.config.simulate:
                self.simulator = SineWaveSimulator(stream_name=self.config.stream_name)
                self.simulator.start()
                # Give LSL a short propagation window before resolving.
                time.sleep(0.15)
                timeout_s = self.config.launch_timeout_s or 5.0
            else:
                port = require_port(self.config.port)
                bridge_path = resolve_bridge_path(self.config.bridge_path)
                command = build_bridge_command(bridge_path, port, self.config.stream_name)
                self.bridge = BridgeProcess(command)
                self.bridge.start()
                timeout_s = self.config.launch_timeout_s or HEALTH_DEFAULTS.launch_timeout_s

            resolved = wait_for_stream_inlet(self.config.stream_name, timeout_s=timeout_s)
            if resolved is None:
                self._degrade(
                    f"stream {self.config.stream_name!r} did not appear within {timeout_s:.1f}s"
                )
                return

            if not self.config.simulate:
                health_check_inlet(resolved, HEALTH_DEFAULTS)

            reader = LSLReader(
                stream_name=self.config.stream_name,
                window_s=self.config.window_s,
                expected_channels=len(CHANNEL_LABELS),
            )
            reader.start(resolved=resolved)
            self.reader = reader
            self.connection_status = "connected"
            self.message = None
        except Exception as exc:
            self._degrade(str(exc))

    def stop(self) -> None:
        if self.reader is not None:
            self.reader.stop()
            self.reader = None
        if self.bridge is not None:
            self.bridge.stop()
            self.bridge = None
        if self.simulator is not None:
            self.simulator.stop()
            self.simulator = None
        self.connection_status = "stopped"
        self._started = False

    def metadata(self) -> dict:
        meta = self._frame_metadata()
        return {
            "stream_name": meta.stream_name,
            "channel_labels": list(meta.channel_labels),
            "sample_rate_hz": meta.sample_rate_hz,
            "source_mode": meta.source_mode,
            "connection_status": meta.connection_status,
            "message": meta.message,
        }

    def health(self) -> dict:
        status = self.connection_status
        message = self.message
        reader_error = self.reader.last_error if self.reader is not None else None
        if reader_error:
            status = "degraded"
            message = reader_error

        bridge_output = self.bridge.output_snapshot() if self.bridge is not None else ""
        bridge_hint = self.bridge.operator_hint() if self.bridge is not None else None
        return {
            "status": status,
            "source_mode": self.source_mode,
            "message": message,
            "reader_running": bool(self.reader and self.reader.is_running),
            "bridge_running": bool(self.bridge and self.bridge.is_running),
            "bridge_returncode": self.bridge.returncode if self.bridge is not None else None,
            "bridge_hint": bridge_hint,
            "bridge_output_tail": bridge_output.splitlines()[-20:],
        }

    def frame(self) -> dict:
        meta = self._frame_metadata()
        if self.reader is None:
            return status_frame(meta, window_s=self.config.window_s)
        if self.reader.last_error:
            meta = FrameMetadata(
                stream_name=meta.stream_name,
                channel_labels=meta.channel_labels,
                sample_rate_hz=meta.sample_rate_hz,
                source_mode=meta.source_mode,
                connection_status="degraded",
                message=self.reader.last_error,
            )
        return build_eeg_frame(self.reader.ring, metadata=meta, window_s=self.config.window_s)

    def inject(self, request: InjectionRequest) -> dict:
        if self.simulator is None:
            raise HTTPException(
                status_code=409,
                detail="simulator injection is only available when running with --simulate",
            )

        if request.state:
            state = self.simulator.inject_state(request.state, duration_s=request.duration_s or 5.0)
            return {"ok": True, "state": state}

        if request.freq_hz is None or request.channel_indices is None:
            raise HTTPException(
                status_code=400,
                detail="provide either a named state or freq_hz plus channel_indices",
            )

        self.simulator.inject_sinusoid(
            freq_hz=request.freq_hz,
            channel_indices=request.channel_indices,
            amplitude=request.amplitude,
            duration_s=request.duration_s,
        )
        return {
            "ok": True,
            "state": "Custom",
            "freq_hz": request.freq_hz,
            "channel_indices": request.channel_indices,
        }

    def _frame_metadata(self) -> FrameMetadata:
        reader = self.reader
        labels = reader.channel_labels if reader is not None else CHANNEL_LABELS
        sample_rate = reader.sample_rate_hz if reader is not None else SAMPLE_RATE_HZ
        return FrameMetadata(
            stream_name=self.config.stream_name,
            channel_labels=tuple(labels),
            sample_rate_hz=float(sample_rate),
            source_mode=self.source_mode,
            connection_status=self.connection_status,
            message=self.message,
        )

    def _degrade(self, message: str) -> None:
        hint = self.bridge.operator_hint() if self.bridge is not None else None
        self.connection_status = "degraded"
        self.message = f"{message} {hint}" if hint else message


def create_app(runtime: AcquisitionRuntime) -> FastAPI:
    """Create the acquisition web app."""

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        runtime.start()
        try:
            yield
        finally:
            runtime.stop()

    app = FastAPI(title="DopaMAXX Acquisition", lifespan=lifespan)

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return _dashboard_html()

    @app.get("/health")
    def health() -> dict:
        return runtime.health()

    @app.get("/metadata")
    def metadata() -> dict:
        return runtime.metadata()

    @app.post("/sim/inject")
    def inject(request: InjectionRequest) -> dict:
        return runtime.inject(request)

    @app.websocket("/stream/eeg")
    async def eeg_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(runtime.frame())
                await asyncio.sleep(0.1)
        except WebSocketDisconnect:
            return

    return app


def _dashboard_html() -> str:
    return (
        resources.files("acquisition")
        .joinpath("static", "dashboard.html")
        .read_text(encoding="utf-8")
    )
