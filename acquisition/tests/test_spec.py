from acquisition.spec import CHANNEL_LABELS, HEALTH_DEFAULTS, SAMPLE_RATE_HZ, STREAM_NAME, STREAM_TYPE


def test_dsi24_constants_match_prd() -> None:
    assert STREAM_NAME == "DSI24-EEG"
    assert STREAM_TYPE == "EEG"
    assert SAMPLE_RATE_HZ == 300.0
    assert len(CHANNEL_LABELS) == 19
    assert CHANNEL_LABELS == (
        "Fp1",
        "Fp2",
        "F7",
        "F3",
        "Fz",
        "F4",
        "F8",
        "T3",
        "C3",
        "Cz",
        "C4",
        "T4",
        "T5",
        "P3",
        "Pz",
        "P4",
        "T6",
        "O1",
        "O2",
    )
    assert len(set(CHANNEL_LABELS)) == 19


def test_health_defaults_match_dsi24_operational_requirements() -> None:
    assert HEALTH_DEFAULTS.launch_timeout_s == 60.0
    assert HEALTH_DEFAULTS.settle_s == 3.0
    assert HEALTH_DEFAULTS.window_s == 2.0
    assert HEALTH_DEFAULTS.min_samples == 300
    assert HEALTH_DEFAULTS.min_rate_hz == 290.0
