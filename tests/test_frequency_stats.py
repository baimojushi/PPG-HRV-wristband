from hrv_app.frequency_stats import compute_frequency_statistics


def test_frequency_statistics_only_use_valid_windows():
    history = [
        {
            "frequency_status": "VALID",
            "vlf_ms2": 100.0,
            "lf_ms2": 200.0,
            "hf_ms2": 100.0,
            "total_power_ms2": 400.0,
            "lf_nu": 66.666,
            "hf_nu": 33.334,
            "lf_hf": 2.0,
            "hf_lf": 0.5,
        },
        {
            "frequency_status": "INVALID",
            "vlf_ms2": 9999.0,
            "lf_ms2": 9999.0,
            "hf_ms2": 9999.0,
            "total_power_ms2": 9999.0,
            "lf_nu": 99.0,
            "hf_nu": 1.0,
            "lf_hf": 99.0,
            "hf_lf": 0.01,
        },
        {
            "frequency_status": "VALID",
            "vlf_ms2": 300.0,
            "lf_ms2": 400.0,
            "hf_ms2": 200.0,
            "total_power_ms2": 900.0,
            "lf_nu": 66.666,
            "hf_nu": 33.334,
            "lf_hf": 2.0,
            "hf_lf": 0.5,
        },
    ]

    stats = compute_frequency_statistics(
        history
    )

    assert stats["valid_window_count"] == 2
    assert stats["total_window_count"] == 3
    assert (
        stats["metrics"]["vlf_ms2"]["mean"]
        == 200.0
    )
    assert (
        stats["metrics"]["lf_hf"]["median"]
        == 2.0
    )
