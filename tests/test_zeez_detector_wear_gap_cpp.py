from pathlib import Path
import shutil
import subprocess

import pytest


def test_short_wear_gap_preserves_rr_prior_but_long_gap_cold_resets(tmp_path: Path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("当前环境没有 g++，跳过 wear-gap host 测试")

    project = Path(__file__).resolve().parents[1]
    lib = project / "firmware" / "lib" / "zeezPPG" / "src"
    harness = tmp_path / "wear_gap.cpp"
    executable = tmp_path / "wear_gap"

    harness.write_text(
        r'''
#include <cmath>
#include <cstdint>
#include <iostream>
#include "zeez_detector.h"

static float pulse(float t_ms, float rr_ms) {
    const float phase = std::fmod(t_ms, rr_ms);
    const float center = 0.32f * rr_ms;
    const float width = 0.085f * rr_ms;
    const float z = (phase - center) / width;
    return 80.0f * std::exp(-0.5f * z * z);
}

int main() {
    ZeezAdaptiveDetector detector(125);
    const float rr_ms = 850.0f;
    uint32_t seq = 0;
    int64_t t_us = 0;

    // 先建立稳定 RR 先验。
    for (int i = 0; i < 2500; ++i) {
        const float t_ms = static_cast<float>(t_us) / 1000.0f;
        detector.update(seq++, t_us, pulse(t_ms, rr_ms), true);
        t_us += 8000;
    }

    const float learned = detector.expectedRRMs();
    if (learned < 650.0f || learned > 1050.0f) {
        std::cerr << "failed to learn RR: " << learned << "\n";
        return 1;
    }

    // 0.5 秒接触抖动：停止输出，但周期先验必须保留。
    for (int i = 0; i < 63; ++i) {
        detector.update(seq++, t_us, 0.0f, false);
        t_us += 8000;
    }
    const float after_short = detector.expectedRRMs();
    if (std::fabs(after_short - learned) > 1.0f) {
        std::cerr << "short gap lost RR prior: " << after_short << "\n";
        return 2;
    }
    if (detector.currentHrBpm() != 0.0f) {
        std::cerr << "HR should be hidden during no-wear\n";
        return 3;
    }

    // 恢复后的第一颗正式心搏只能重新锚定相位，不能跨 no-wear 计算 RR。
    bool got_first_after_resume = false;
    for (int i = 0; i < 500; ++i) {
        const float t_ms = static_cast<float>(t_us) / 1000.0f;
        const ZeezDetectorEvent event = detector.update(
            seq++, t_us, pulse(t_ms, rr_ms), true
        );
        t_us += 8000;
        if (event.accepted) {
            got_first_after_resume = true;
            if (event.rr_ms != 0) {
                std::cerr << "RR crossed short no-wear gap: " << event.rr_ms << "\n";
                return 4;
            }
            break;
        }
    }
    if (!got_first_after_resume) {
        std::cerr << "detector did not reacquire after short gap\n";
        return 5;
    }

    // 新的一段无佩戴持续到 >2 秒：此时才做真正冷启动。
    for (int i = 0; i < 270; ++i) {
        detector.update(seq++, t_us, 0.0f, false);
        t_us += 8000;
    }
    if (detector.expectedRRMs() != 0.0f) {
        std::cerr << "long gap did not cold reset\n";
        return 6;
    }

    return 0;
}
''',
        encoding="utf-8",
    )

    build = subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-O2",
            "-I",
            str(lib),
            str(lib / "zeez_detector.cpp"),
            str(harness),
            "-o",
            str(executable),
        ],
        text=True,
        capture_output=True,
    )
    assert build.returncode == 0, build.stdout + "\n" + build.stderr

    run = subprocess.run([str(executable)], text=True, capture_output=True)
    assert run.returncode == 0, run.stdout + "\n" + run.stderr
