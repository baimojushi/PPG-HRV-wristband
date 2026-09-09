from __future__ import annotations

from collections.abc import Sequence
import math
import numpy as np

from .config import AnalysisConfig
from .models import FrequencyDomainMetrics


AUTONOMIC_ZONES = (
    {
        "name": "较慢起伏区",
        "low_hz": 0.04,
        "high_hz": 0.10,
        "rgb": (214, 122, 86),
        "meaning": "较慢的心率起伏，常会受到呼吸速度、姿势和压力变化影响。",
    },
    {
        "name": "中间起伏区",
        "low_hz": 0.10,
        "high_hz": 0.20,
        "rgb": (196, 167, 92),
        "meaning": "介于慢节律与呼吸相关快节律之间的过渡区域。",
    },
    {
        "name": "呼吸相关快起伏区",
        "low_hz": 0.20,
        "high_hz": 0.40,
        "rgb": (96, 155, 124),
        "meaning": "较快的心率起伏，很多时候会跟着呼吸一起变化。",
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
        return {
            'headline': '这5分钟还不适合解读快慢节律。',
            'plain_text': '继续保持手腕放松和腕带贴合，积累到足够连续、清晰的数据后会自动更新。',
            'vlf_text': '很慢的背景变化：等待更连续的数据。',
            'lf_text': '较慢的心率起伏：等待更连续的数据。',
            'hf_text': '呼吸相关的较快起伏：等待更连续的数据。',
            'median_text': '整体快慢位置：等待更连续的数据。',
            'welch_text': '这张图会把最近5分钟的心跳起伏按快慢摊开；峰越高，说明那个节奏越明显。',
            'spwvd_text': '这张图会把最近5分钟铺开来看；越亮的地方，表示那种快慢节奏在那个时刻越明显。',
        }

    total = max(float(frequency.total_power_ms2), 1e-12)
    vlf_share = _safe_share(frequency.vlf_ms2, total)
    lf_share = _safe_share(frequency.lf_ms2, total)
    hf_share = _safe_share(frequency.hf_ms2, total)
    median_mhz = float(frequency.median_frequency_hz * 1000.0)

    band_map = {
        'very_slow': frequency.vlf_ms2,
        'slow': frequency.lf_ms2,
        'fast': frequency.hf_ms2,
    }
    dominant = max(band_map, key=band_map.get)

    if median_mhz < 80.0:
        median_phrase = '整体更偏慢，缓慢的起伏更明显。'
    elif median_mhz < 180.0:
        median_phrase = '整体处在中间位置，较慢和较快的起伏都在参与。'
    else:
        median_phrase = '整体更偏快，跟呼吸一起变化的起伏更明显。'

    dominant_text = {
        'very_slow': '现在最明显的是很慢的背景变化。',
        'slow': '现在最明显的是较慢的心率起伏。',
        'fast': '现在最明显的是较快、常跟呼吸一起变化的起伏。',
    }[dominant]

    return {
        'headline': dominant_text,
        'plain_text': (
            f'很慢的背景变化约 {vlf_share:.0f}% · '
            f'较慢起伏约 {lf_share:.0f}% · '
            f'呼吸相关快起伏约 {hf_share:.0f}%。'
            f'{median_phrase}'
        ),
        'vlf_text': (
            f'很慢的背景变化约占 {vlf_share:.0f}%。'
            '它更适合用来观察缓慢的身体变化，不单独代表某一种情绪或神经状态。'
        ),
        'lf_text': (
            f'较慢的心率起伏约占 {lf_share:.0f}%。'
            '它会受到呼吸速度、姿势、压力变化等多种因素影响。'
        ),
        'hf_text': (
            f'呼吸相关的较快起伏约占 {hf_share:.0f}%。'
            '这部分很多时候会随着呼吸一起变强或变弱。'
        ),
        'median_text': (
            '整体快慢位置：' + median_phrase
        ),
        'welch_text': (
            '这张图把最近5分钟的心跳起伏按快慢摊开。峰越高，说明那个节奏越明显；'
            '它只描述节律形状，不直接判断情绪状态。'
        ),
        'spwvd_text': (
            '这张图把最近5分钟铺开来看：越亮的地方，表示那种快慢节奏在那个时刻更明显。'
            '很暗的区域只表示显示值较弱，不需要把单个色块理解成身体结论。'
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
            'name': '很慢的背景变化',
            'low_hz': cfg.vlf_low_hz,
            'high_hz': cfg.vlf_high_hz,
            'rgb': NEUTRAL_VLF_RGB,
        },
        *AUTONOMIC_ZONES,
    ]
