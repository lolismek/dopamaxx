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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from acquisition.autoscroll import AutoscrollService
from acquisition.bridge import BridgeProcess, build_bridge_command
from acquisition.config import BridgeConfigError, require_port, resolve_bridge_path
from acquisition.content_models import (
    AutoscrollCancelRequest,
    AutoscrollStartRequest,
    ForYouCandidatesIngestRequest,
    PostReaction,
    QueueStatusUpdateRequest,
    ReactionIngestRequest,
    utc_now_iso,
)
from acquisition.content_store import ContentStore, content_store_from_env
from acquisition.for_you_source import ForYouCandidateSource
from acquisition.frames import FrameMetadata, build_eeg_frame, status_frame
from acquisition.lsl import LSLReader, health_check_inlet, wait_for_stream_inlet
from acquisition.raw_stream import encode_raw_frame, hello_message
from acquisition.scoring import EmbeddingProvider, embedding_provider_from_env
from acquisition.simulator import SineWaveSimulator
from acquisition.spec import CHANNEL_LABELS, HEALTH_DEFAULTS, SAMPLE_RATE_HZ, STREAM_NAME
from acquisition.twitter_mcp import CandidateSource, twitter_mcp_from_env

REWARD_HIT_THRESHOLD = 0.35
REWARD_MISS_THRESHOLD = -0.25


@dataclass(frozen=True)
class RuntimeConfig:
    simulate: bool = False
    port: str | None = None
    bridge_path: str | Path | None = None
    stream_name: str = STREAM_NAME
    window_s: float = 5.0
    inference_window_s: float = 1.5
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
            "window_s": self.config.window_s,
            "inference_window_s": self.config.inference_window_s,
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
            return status_frame(
                meta,
                window_s=self.config.window_s,
                inference_window_s=self.config.inference_window_s,
            )
        if self.reader.last_error:
            meta = FrameMetadata(
                stream_name=meta.stream_name,
                channel_labels=meta.channel_labels,
                sample_rate_hz=meta.sample_rate_hz,
                source_mode=meta.source_mode,
                connection_status="degraded",
                message=self.reader.last_error,
            )
        return build_eeg_frame(
            self.reader.ring,
            metadata=meta,
            window_s=self.config.window_s,
            inference_window_s=self.config.inference_window_s,
        )

    def raw_stream_metadata(self) -> dict:
        return self.metadata() | {
            "recommended_url": "/stream/raw",
            "json_fallback_url": "/stream/raw-json",
        }

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


def create_app(
    runtime: AcquisitionRuntime,
    *,
    content_store: ContentStore | None = None,
    candidate_source: CandidateSource | None = None,
    embedder: EmbeddingProvider | None = None,
) -> FastAPI:
    """Create the acquisition web app."""

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        runtime.start()
        try:
            yield
        finally:
            runtime.stop()

    app = FastAPI(title="DopaMAXX Acquisition", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    store = content_store or content_store_from_env()
    post_embedder = embedder or embedding_provider_from_env()
    live_candidate_source = candidate_source or twitter_mcp_from_env()
    for_you_candidates = ForYouCandidateSource(fallback=live_candidate_source)
    autoscroll = AutoscrollService(
        store=store,
        candidate_source=for_you_candidates,
        embedder=post_embedder,
    )

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return _dashboard_html()

    @app.get("/microdose/feed", response_class=HTMLResponse)
    def microdose_feed_page() -> str:
        return _microdose_feed_html()

    @app.get("/health")
    def health() -> dict:
        return runtime.health()

    @app.get("/metadata")
    def metadata() -> dict:
        return runtime.metadata()

    @app.get("/stream/raw-info")
    def raw_info() -> dict:
        return hello_message(runtime.raw_stream_metadata())

    @app.post("/sim/inject")
    def inject(request: InjectionRequest) -> dict:
        return runtime.inject(request)

    @app.post("/locked-out/reactions")
    async def ingest_reaction(request: ReactionIngestRequest) -> dict:
        reaction = PostReaction(
            user_id=request.user_id,
            session_id=request.session_id,
            post_id=request.post.post_id,
            text=request.post.text,
            author=request.post.author,
            url=request.post.url,
            media_urls=request.post.media_urls,
            embedding=[],
            reward_score=request.reward_score,
            focus_score=request.focus_score,
            label=request.resolved_label(REWARD_HIT_THRESHOLD, REWARD_MISS_THRESHOLD),
            dwell_ms=request.dwell_ms,
            eeg_features=request.eeg_features,
            metadata={"post_metadata": request.post.metadata, "source": request.post.source},
        )
        stored = await store.insert_reaction(reaction)
        return {"reaction": stored.model_dump(mode="json")}

    @app.post("/feed/for-you/candidates")
    async def ingest_for_you_candidates(request: ForYouCandidatesIngestRequest) -> dict:
        accepted_count = await for_you_candidates.ingest(
            user_id=request.user_id,
            session_id=request.session_id,
            posts=request.posts,
            observed_at=request.observed_at,
        )
        buffered_count = await for_you_candidates.count(
            user_id=request.user_id,
            session_id=request.session_id,
        )
        return {
            "ok": True,
            "accepted_count": accepted_count,
            "buffered_count": buffered_count,
        }

    @app.post("/agent/autoscroll/start")
    async def start_autoscroll(request: AutoscrollStartRequest) -> dict:
        try:
            run = await autoscroll.start(request)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"run": run.model_dump(mode="json")}

    @app.post("/agent/autoscroll/cancel")
    async def cancel_autoscroll(request: AutoscrollCancelRequest) -> dict:
        run = await autoscroll.cancel(request.run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        return {"run": run.model_dump(mode="json")}

    @app.get("/agent/autoscroll/runs/{run_id}")
    async def get_autoscroll_run(run_id: str) -> dict:
        run = await store.get_agent_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="agent run not found")
        return {"run": run.model_dump(mode="json")}

    @app.get("/feed/microdose")
    async def microdose_feed(
        user_id: str,
        session_id: str,
        limit: int = 100,
        run_id: str | None = None,
    ) -> dict:
        items = await store.list_ready_queue(
            user_id=user_id,
            session_id=session_id,
            limit=limit,
            run_id=run_id,
        )
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "refreshed_at": utc_now_iso(),
        }

    @app.patch("/feed/microdose/{queue_id}")
    async def update_microdose_item(queue_id: str, request: QueueStatusUpdateRequest) -> dict:
        item = await store.update_queue_status(queue_id, request.status)
        if item is None:
            raise HTTPException(status_code=404, detail="queued item not found")
        return {"item": item.model_dump(mode="json")}

    @app.websocket("/stream/eeg")
    async def eeg_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(runtime.frame())
                await asyncio.sleep(0.1)
        except WebSocketDisconnect:
            return

    @app.websocket("/stream/raw")
    async def raw_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        query = websocket.query_params
        max_samples = _bounded_int(query.get("max_samples"), default=256, low=1, high=4096)
        poll_ms = _bounded_float(query.get("poll_ms"), default=2.0, low=1.0, high=100.0)
        replay = query.get("replay", "0") in {"1", "true", "yes"}
        await websocket.send_json(hello_message(runtime.raw_stream_metadata()))
        try:
            reader = runtime.reader
            if reader is None:
                await websocket.close(code=1013, reason="acquisition not connected")
                return
            last_sequence = 0 if replay else reader.ring.total_written
            while True:
                reader = runtime.reader
                if reader is None:
                    await websocket.close(code=1013, reason="acquisition stopped")
                    return
                samples, ts, first_sequence, next_sequence, dropped = reader.ring.read_since(
                    last_sequence,
                    max_samples=max_samples,
                )
                if samples.shape[0] > 0:
                    payload = encode_raw_frame(
                        samples,
                        ts,
                        stream_name=runtime.config.stream_name,
                        channel_labels=reader.channel_labels,
                        sample_rate_hz=reader.sample_rate_hz,
                        first_sequence=first_sequence,
                        next_sequence=next_sequence,
                        dropped=dropped,
                    )
                    await websocket.send_bytes(payload)
                    last_sequence = next_sequence
                else:
                    last_sequence = next_sequence
                    await asyncio.sleep(poll_ms / 1000.0)
        except WebSocketDisconnect:
            return

    @app.websocket("/stream/raw-json")
    async def raw_json_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        query = websocket.query_params
        max_samples = _bounded_int(query.get("max_samples"), default=64, low=1, high=512)
        poll_ms = _bounded_float(query.get("poll_ms"), default=10.0, low=2.0, high=250.0)
        replay = query.get("replay", "0") in {"1", "true", "yes"}
        try:
            reader = runtime.reader
            if reader is None:
                await websocket.close(code=1013, reason="acquisition not connected")
                return
            last_sequence = 0 if replay else reader.ring.total_written
            while True:
                reader = runtime.reader
                if reader is None:
                    await websocket.close(code=1013, reason="acquisition stopped")
                    return
                samples, ts, first_sequence, next_sequence, dropped = reader.ring.read_since(
                    last_sequence,
                    max_samples=max_samples,
                )
                if samples.shape[0] > 0:
                    await websocket.send_json(
                        {
                            "type": "raw_eeg_chunk",
                            "stream_name": runtime.config.stream_name,
                            "channel_labels": list(reader.channel_labels),
                            "sample_rate_hz": reader.sample_rate_hz,
                            "first_sequence": first_sequence,
                            "next_sequence": next_sequence,
                            "dropped": dropped,
                            "timestamps": ts.tolist(),
                            "samples": samples.tolist(),
                        }
                    )
                    last_sequence = next_sequence
                else:
                    last_sequence = next_sequence
                    await asyncio.sleep(poll_ms / 1000.0)
        except WebSocketDisconnect:
            return

    return app


def _bounded_int(raw: str | None, *, default: int, low: int, high: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        value = default
    return max(low, min(high, value))


def _bounded_float(raw: str | None, *, default: float, low: float, high: float) -> float:
    try:
        value = float(raw) if raw is not None else default
    except ValueError:
        value = default
    return max(low, min(high, value))


def _dashboard_html() -> str:
    return (
        resources.files("acquisition")
        .joinpath("static", "dashboard.html")
        .read_text(encoding="utf-8")
    )


def _microdose_feed_html() -> str:
    return (
        resources.files("acquisition")
        .joinpath("static", "microdose_feed.html")
        .read_text(encoding="utf-8")
    )
