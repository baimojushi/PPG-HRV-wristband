from __future__ import annotations

from collections.abc import Sequence
import math
import numpy as np

from .config import AnalysisConfig
from .models import FrequencyDomainMetrics


AUTONOMIC_ZONES = (
    {
        "name": "交感偏主带",
        "low_hz": 0.04,
        "high_hz": 0.10,
        "rgb": (214, 122, 86),
        "meaning": "更偏向缓慢调节、血压反射和交感参与的低频摆动。",
    },
    {
        "name": "交感-副交感共调带",
        "low_hz": 0.10,
        "high_hz": 0.20,
        "rgb": (196, 167, 92),
        "meaning": "两套神经调节共同参与的过渡带。",
    },
    {
        "name": "副交感偏主带",
        "low_hz": 0.20,
        "high_hz": 0.40,
        "rgb": (96, 155, 124),
        "meaning": "更偏向呼吸相关快波动和副交感参与。",
    },
)

NEUTRAL_VLF_RGB = (184, 176, 168)


def compute_median_frequency_hz(
    freqs_hz: np.ndarray,
    psd_ms2_hz: np.ndarray,
) -> float:
    freqs = np.asarray(freqs_hz, dtype=float)
    psd = np.asarray(psd_ms2_hz, dtype=float)

    if freqs.size < 2 or psd.size != freqs.size:
        return 0.0

    mask = np.isfinite(freqs) & np.isfinite(psd) & (psd >= 0.0)
    freqs = freqs[mask]
    psd = psd[mask]

    if freqs.size < 2:
        return 0.0

    diffs = np.diff(freqs)
    segment_area = 0.5 * (psd[:-1] + psd[1:]) * diffs
    cumulative = np.concatenate(([0.0], np.cumsum(segment_area)))

    total = float(cumulative[-1])
    if not math.isfinite(total) or total <= 1e-12:
        return 0.0

    target = total * 0.5
    index = int(np.searchsorted(cumulative, target, side='left'))
    index = min(max(index, 1), freqs.size - 1)

    area0 = cumulative[index - 1]
    area1 = cumulative[index]
    freq0 = float(freqs[index - 1])
    freq1 = float(freqs[index])

    if area1 <= area0 + 1e-12:
        return freq1

    weight = (target - area0) / (area1 - area0)
    return float(freq0 + (freq1 - freq0) * weight)



def _safe_share(value: float, total: float) -> float:
    if not math.isfinite(total) or total <= 1e-12:
        return 0.0
    return float(np.clip(value / total * 100.0, 0.0, 100.0))



def describe_frequency_balance(
    frequency: FrequencyDomainMetrics,
) -> dict:
    if not frequency.valid:
        reason = frequency.validity_reason or '频域窗口尚未达到可解释条件'
        return {
            'headline': '自动解析：当前还不能可靠解释频域分布。',
            'plain_text': reason,
            'vlf_text': 'VLF：等待有效频域窗口。',
            'lf_text': 'LF：等待有效频域窗口。',
            'hf_text': 'HF：等待有效频域窗口。',
            'median_text': '中位频率：等待有效频域窗口。',
            'welch_text': 'Welch 功率谱：质量门通过后再解释频带能量。',
            'spwvd_text': 'SPWVD：质量门通过后再观察时频结构。',
        }

    total = max(float(frequency.total_power_ms2), 1e-12)
    vlf_share = _safe_share(frequency.vlf_ms2, total)
    lf_share = _safe_share(frequency.lf_ms2, total)
    hf_share = _safe_share(frequency.hf_ms2, total)
    median_mhz = float(frequency.median_frequency_hz * 1000.0)

    band_map = {
        'VLF': frequency.vlf_ms2,
        'LF': frequency.lf_ms2,
        'HF': frequency.hf_ms2,
    }
    dominant = max(band_map, key=band_map.get)

    if median_mhz < 80.0:
        median_phrase = '频谱能量重心偏低，说明慢节律摆动更明显。'
    elif median_mhz < 180.0:
        median_phrase = '频谱能量重心位于中间带，低频与高频都在参与。'
    else:
        median_phrase = '频谱能量重心偏高，说明呼吸相关快波动更明显。'

    dominant_text = {
        'VLF': '当前总功率更多落在极慢变化带，常见于较缓慢的趋势波动。',
        'LF': '当前总功率更多落在 LF，常见于交感参与与压力反射节律较明显。',
        'HF': '当前总功率更多落在 HF，常见于呼吸驱动与副交感参与较明显。',
    }[dominant]

    return {
        'headline': (
            f'自动解析：{dominant_text} '
            f'LF/HF {frequency.lf_hf:.2f}，中位频率 {median_mhz:.1f} mHz。'
        ),
        'plain_text': (
            f'VLF {vlf_share:.1f}% · LF {lf_share:.1f}% · HF {hf_share:.1f}% ；'
            f'{median_phrase}'
        ),
        'vlf_text': (
            f'VLF：{frequency.vlf_ms2:.1f} ms²，占总功率 {vlf_share:.1f}%。'
            '它更多反映极慢的节律背景，适合看缓慢趋势，不单独等同于某一神经强弱。'
        ),
        'lf_text': (
            f'LF：{frequency.lf_ms2:.1f} ms²，占总功率 {lf_share:.1f}%。'
            '它常与压力反射、体位调节和交感参与共同相关。'
        ),
        'hf_text': (
            f'HF：{frequency.hf_ms2:.1f} ms²，占总功率 {hf_share:.1f}%。'
            '它常与呼吸相关波动和副交感参与更接近。'
        ),
        'median_text': (
            f'中位频率：{median_mhz:.1f} mHz。'
            + median_phrase
        ),
        'welch_text': (
            'Welch 功率谱用于看“哪些频率最有能量”。色带只表示神经意义的观察区间，'
            '不是诊断结论。'
        ),
        'spwvd_text': (
            'SPWVD 用于看“这些能量在 5 分钟内何时增强”。橙色偏交感、金色共调、'
            '绿色偏副交感；VLF 仍保留为慢变背景。'
        ),
    }



def build_frequency_trend_rows(history: Sequence[dict]) -> list[dict]:
    valid_rows = [
        row
        for row in history
        if row.get('frequency_status') in {'VALID', 'LIMITED'}
        and np.isfinite(row.get('vlf_ms2', np.nan))
        and np.isfinite(row.get('lf_ms2', np.nan))
        and np.isfinite(row.get('hf_ms2', np.nan))
        and np.isfinite(row.get('median_frequency_hz', np.nan))
    ]

    if not valid_rows:
        return []

    t0 = valid_rows[0].get('t_us', 0)
    trend_rows: list[dict] = []
    for row in valid_rows:
        trend_rows.append({
            't_us': int(row.get('t_us', 0)),
            'elapsed_minutes': float((row.get('t_us', 0) - t0) / 60e6),
            'frequency_status': row.get('frequency_status', ''),
            'total_power_ms2': float(row.get('total_power_ms2', 0.0)),
            'vlf_ms2': float(row.get('vlf_ms2', 0.0)),
            'lf_ms2': float(row.get('lf_ms2', 0.0)),
            'hf_ms2': float(row.get('hf_ms2', 0.0)),
            'lf_hf': float(row.get('lf_hf', 0.0)),
            'median_frequency_hz': float(row.get('median_frequency_hz', 0.0)),
            'median_frequency_mhz': float(row.get('median_frequency_hz', 0.0) * 1000.0),
        })
    return trend_rows



def frequency_zone_brushes(config: AnalysisConfig | None = None) -> list[dict]:
    cfg = config or AnalysisConfig()
    return [
        {
            'name': 'VLF慢变背景',
            'low_hz': cfg.vlf_low_hz,
            'high_hz': cfg.vlf_high_hz,
            'rgb': NEUTRAL_VLF_RGB,
        },
        *AUTONOMIC_ZONES,
    ]
