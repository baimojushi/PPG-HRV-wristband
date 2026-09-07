import numpy as np

from hrv_app.frequency_insights import (
    build_frequency_trend_rows,
    compute_median_frequency_hz,
    describe_frequency_balance,
)
from hrv_app.models import FrequencyDomainMetrics


def test_compute_median_frequency_hz_returns_half_power_location():
    freqs = np.asarray([0.04, 0.10, 0.20, 0.30], dtype=float)
    psd = np.asarray([1.0, 3.0, 2.0, 0.0], dtype=float)

    median = compute_median_frequency_hz(freqs, psd)

    assert 0.10 < median < 0.20


def test_build_frequency_trend_rows_keeps_median_frequency():
    rows = build_frequency_trend_rows([
        {
            't_us': 100_000_000,
            'frequency_status': 'VALID',
            'total_power_ms2': 10.0,
            'vlf_ms2': 1.0,
            'lf_ms2': 4.0,
            'hf_ms2': 5.0,
            'lf_hf': 0.8,
            'median_frequency_hz': 0.18,
        },
        {
            't_us': 160_000_000,
            'frequency_status': 'LIMITED',
            'total_power_ms2': 12.0,
            'vlf_ms2': 2.0,
            'lf_ms2': 5.0,
            'hf_ms2': 5.0,
            'lf_hf': 1.0,
            'median_frequency_hz': 0.20,
        },
    ])

    assert len(rows) == 2
    assert rows[0]['elapsed_minutes'] == 0.0
    assert rows[1]['elapsed_minutes'] == 1.0
    assert rows[1]['median_frequency_mhz'] == 200.0


def test_describe_frequency_balance_uses_plain_language():
    insight = describe_frequency_balance(
        FrequencyDomainMetrics(
            valid=True,
            status='VALID',
            total_power_ms2=1000.0,
            vlf_ms2=150.0,
            lf_ms2=550.0,
            hf_ms2=300.0,
            lf_hf=1.83,
            median_frequency_hz=0.14,
        )
    )

    assert '自动解析' in insight['headline']
    assert 'LF' in insight['lf_text']
    assert '中位频率' in insight['median_text']
