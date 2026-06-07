from __future__ import annotations

import json
from pathlib import Path

from acquisition.spec import CHANNEL_LABELS, SAMPLE_RATE_HZ, STREAM_NAME


def test_locked_out_eeg_contract_matches_acquisition_spec() -> None:
    contract_path = Path(__file__).resolve().parents[1] / "eeg_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    assert contract["acquisition_schema"] == "acquisition.websocket.eeg_frame.v1"
    assert contract["stream_name"] == STREAM_NAME
    assert contract["sample_rate_hz"] == SAMPLE_RATE_HZ
    assert tuple(contract["channel_labels"]) == CHANNEL_LABELS
    assert contract["source_mode"] in contract["allowed_source_modes"]
    assert contract["reward_source"] in {"acquisition_inference_v1", "random_v0"}
    assert -1 <= contract["reward_score"] <= 1
    assert 0 <= contract["focus_score"] <= 1
    assert contract["reward_label"] in {"hit", "miss", "neutral"}
