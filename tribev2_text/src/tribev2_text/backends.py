"""Prediction backends for text signatures."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class PredictionResult:
    """Predicted brain activation returned by a backend."""

    predictions: Any
    backend: str
    model_id: str


class TextPredictionBackend(Protocol):
    """Backend interface used by the signature builder."""

    backend: str
    model_id: str

    def predict(
        self,
        text: str,
        events: Sequence[Mapping[str, Any]],
    ) -> PredictionResult:
        """Return predicted activation for normalized text and events."""


class DeterministicFakeBackend:
    """Small deterministic backend for tests and CLI smoke checks."""

    backend = "fake"
    model_id = "deterministic-fake-v1"

    def __init__(self, timesteps: int = 4, vertices: int = 64) -> None:
        if timesteps <= 0:
            raise ValueError("timesteps must be positive")
        if vertices <= 0:
            raise ValueError("vertices must be positive")
        self.timesteps = timesteps
        self.vertices = vertices

    def predict(
        self,
        text: str,
        events: Sequence[Mapping[str, Any]],
    ) -> PredictionResult:
        event_seed = "|".join(str(event.get("text", "")) for event in events)
        seed = f"{text}\n{event_seed}".encode("utf-8")
        rows: list[list[float]] = []
        for timestep in range(self.timesteps):
            row = []
            for vertex in range(self.vertices):
                digest = blake2b(
                    seed + f":{timestep}:{vertex}".encode("ascii"),
                    digest_size=8,
                ).digest()
                raw = int.from_bytes(digest, "big") / ((1 << 64) - 1)
                row.append(raw * 2.0 - 1.0)
            rows.append(row)
        return PredictionResult(
            predictions=rows,
            backend=self.backend,
            model_id=self.model_id,
        )


class TribeV2Backend:
    """Lazy real TRIBE v2 backend using synthetic word events."""

    backend = "tribev2"

    def __init__(
        self,
        model_id: str = "facebook/tribev2",
        cache_folder: str | Path = "tribev2_text/.cache",
        device: str = "auto",
        checkpoint_name: str = "best.ckpt",
    ) -> None:
        self.model_id = model_id
        self.cache_folder = Path(cache_folder)
        self.device = device
        self.checkpoint_name = checkpoint_name
        self._model: Any = None

    def predict(
        self,
        text: str,
        events: Sequence[Mapping[str, Any]],
    ) -> PredictionResult:
        del text
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError(
                "pandas is required for the real TRIBE v2 backend. "
                "Install this package with the 'tribe' extra."
            ) from exc

        model = self._load_model()
        events_df = pd.DataFrame(list(events))
        predictions, _segments = model.predict(events=events_df, verbose=False)
        return PredictionResult(
            predictions=predictions,
            backend=self.backend,
            model_id=self.model_id,
        )

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from tribev2 import TribeModel
        except ImportError as exc:
            raise RuntimeError(
                "tribev2 is required for the real backend. Install this "
                "package with the 'tribe' extra and authenticate with "
                "Hugging Face if using gated Llama text features."
            ) from exc

        self.cache_folder.mkdir(parents=True, exist_ok=True)
        self._model = TribeModel.from_pretrained(
            self.model_id,
            checkpoint_name=self.checkpoint_name,
            cache_folder=self.cache_folder,
            device=self.device,
        )
        return self._model

