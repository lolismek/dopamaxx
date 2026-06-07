from __future__ import annotations

import numpy as np

from acquisition.lsl import scalp_channel_indices
from acquisition.quality import quality_flags
from acquisition.spec import CHANNEL_LABELS


def test_scalp_channel_indices_maps_vendor_24_channel_order_to_canonical_19() -> None:
    vendor_labels = (
        "P3",
        "C3",
        "F3",
        "Fz",
        "F4",
        "C4",
        "P4",
        "Cz",
        "Pz",
        "Fp1",
        "Fp2",
        "T3",
        "T5",
        "O1",
        "O2",
        "X3",
        "X2",
        "F7",
        "F8",
        "X1",
        "A2",
        "T6",
        "T4",
        "TRG",
    )

    indices = scalp_channel_indices(vendor_labels)

    assert indices is not None
    assert tuple(vendor_labels[i] for i in indices) == CHANNEL_LABELS


def test_quality_clipping_ignores_large_dc_offsets() -> None:
    samples = np.array(
        [
            [10000.0, 0.0],
            [10001.0, 10.0],
            [9999.0, -10.0],
        ]
    )

    quality = quality_flags(samples, ("Cz", "Fz"), clip_deviation_threshold=100.0)

    assert quality["clip_channel_labels"] == []
