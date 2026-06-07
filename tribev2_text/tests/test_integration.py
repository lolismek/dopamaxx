from __future__ import annotations

import os

import pytest

from tribev2_text import TribeV2Backend, encode_text


@pytest.mark.skipif(
    os.environ.get("RUN_TRIBEV2_INTEGRATION") != "1",
    reason="set RUN_TRIBEV2_INTEGRATION=1 to run real TRIBE v2 inference",
)
def test_real_tribev2_backend_short_text() -> None:
    signature = encode_text(
        "A concise text-only post for TRIBE v2.",
        backend=TribeV2Backend(cache_folder=".cache"),
    )
    assert signature.backend == "tribev2"
    assert signature.prediction_shape[0] > 0
    assert signature.prediction_shape[1] > 0
    assert len(signature.similarity_vector) == 1536

