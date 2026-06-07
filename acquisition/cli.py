"""CLI for the DopaMAXX acquisition service."""

from __future__ import annotations

from pathlib import Path

import typer

from acquisition.service import AcquisitionRuntime, RuntimeConfig, create_app
from acquisition.spec import STREAM_NAME

app = typer.Typer(no_args_is_help=True, help="DopaMAXX DSI-24 acquisition service.")


@app.callback()
def _root() -> None:
    """DopaMAXX DSI-24 acquisition commands."""


@app.command()
def serve(
    simulate: bool = typer.Option(False, "--simulate", help="Publish and consume synthetic DSI-24 EEG."),
    port: str | None = typer.Option(None, "--port", help="DSI-24 serial/COM port for real hardware."),
    host: str = typer.Option("127.0.0.1", "--host", help="HTTP bind host."),
    http_port: int = typer.Option(8000, "--http-port", help="HTTP bind port."),
    stream_name: str = typer.Option(STREAM_NAME, "--stream-name", help="LSL stream name."),
    window_s: float = typer.Option(5.0, "--window-s", help="Rolling EEG window length."),
    inference_window_s: float = typer.Option(
        1.5,
        "--inference-window-s",
        help="Recent EEG window length for focus/reward inference.",
    ),
    bridge_path: Path | None = typer.Option(None, "--bridge-path", help="Absolute path to dsi2lsl.exe."),
) -> None:
    """Serve the live acquisition dashboard and WebSocket stream."""

    import uvicorn

    runtime = AcquisitionRuntime(
        RuntimeConfig(
            simulate=simulate,
            port=port,
            bridge_path=bridge_path,
            stream_name=stream_name,
            window_s=window_s,
            inference_window_s=inference_window_s,
        )
    )
    app_obj = create_app(runtime)
    typer.echo(f"Serving DopaMAXX acquisition at http://{host}:{http_port}")
    uvicorn.run(app_obj, host=host, port=http_port)


def main() -> None:
    app()
