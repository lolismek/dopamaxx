"""Host-specific acquisition configuration."""

from __future__ import annotations

import os
from pathlib import Path

DOPAMAXX_DSI_BRIDGE_ENV = "DOPAMAXX_DSI_BRIDGE_PATH"
RLHB_DSI_BRIDGE_ENV = "RLHB_DSI_BRIDGE_PATH"


class BridgeConfigError(ValueError):
    """Raised when the real DSI bridge cannot be configured safely."""


def resolve_bridge_path(override: str | Path | None = None) -> Path:
    """Resolve the dsi2lsl executable path for real hardware mode.

    DopaMAXX intentionally requires an absolute path. The Wearable Sensing
    executable loads co-located DLLs, and resolving a bare executable name from
    an arbitrary process cwd can silently break those DLL lookups.
    """

    raw: str | Path | None = override
    if raw is None:
        raw = os.environ.get(DOPAMAXX_DSI_BRIDGE_ENV)
    if raw is None:
        raw = os.environ.get(RLHB_DSI_BRIDGE_ENV)
    if raw is None or str(raw).strip() == "":
        raise BridgeConfigError(
            "real DSI-24 mode requires an absolute dsi2lsl.exe path via "
            "--bridge-path, DOPAMAXX_DSI_BRIDGE_PATH, or RLHB_DSI_BRIDGE_PATH"
        )

    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise BridgeConfigError(
            "dsi2lsl.exe path must be absolute so its co-located DLLs load reliably"
        )
    return path


def require_port(port: str | None) -> str:
    """Validate the operator-supplied serial/COM port for real mode."""

    if port is None or not port.strip():
        raise BridgeConfigError("real DSI-24 mode requires an explicit --port such as COM3")
    return port.strip()
