from pathlib import Path
import shutil
import subprocess

import pytest


def test_zeez_detector_host_cpp(tmp_path: Path):
    compiler = shutil.which("g++")

    if compiler is None:
        pytest.skip(
            "当前环境没有 g++，跳过 zeez_detector host 测试"
        )

    project = Path(__file__).resolve().parents[1]
    lib = (
        project
        / "firmware"
        / "lib"
        / "zeezPPG"
        / "src"
    )

    harness = (
        tmp_path
        / "zeez_detector_harness.cpp"
    )
    executable = (
        tmp_path
        / "zeez_detector_harness"
    )

    harness.write_text(
        r'''
#include <cmath>
#include <cstdint>
#include <iostream>
#include <vector>

#include "zeez_detector.h"

static float pulseWave(
    float phase_ms,
    float rr_ms,
    float amplitude
) {
    const float main_center =
        0.32f * rr_ms;

    const float shoulder_center =
        0.53f * rr_ms;

    const float main_width =
        0.085f * rr_ms;

    const float shoulder_width =
        0.055f * rr_ms;

    const float main_z =
        (phase_ms - main_center)
        / main_width;

    const float shoulder_z =
        (phase_ms - shoulder_center)
        / shoulder_width;

    const float main =
        amplitude
        * std::exp(
            -0.5f
            * main_z
            * main_z
        );

    const float shoulder =
        0.33f
        * amplitude
        * std::exp(
            -0.5f
            * shoulder_z
            * shoulder_z
        );

    return (
        80.0f * main
        + 22.0f * shoulder
    );
}

static bool runCase(
    float rr_ms,
    float duration_s,
    float min_hr,
    float max_hr,
    bool modulation
) {
    ZeezAdaptiveDetector detector(125);

    std::vector<float> rr_values;
    int candidate_count = 0;
    int accepted_count = 0;

    const int total_samples =
        static_cast<int>(
            duration_s * 125.0f
        );

    for (
        int i = 0;
        i < total_samples;
        ++i
    ) {
        const float t_ms =
            static_cast<float>(i)
            * 8.0f;

        const float phase =
            std::fmod(
                t_ms,
                rr_ms
            );

        float amplitude = 1.0f;

        if (modulation) {
            amplitude =
                0.55f
                + 0.55f
                * (
                    0.5f
                    + 0.5f
                    * std::sin(
                        2.0f
                        * 3.1415926535f
                        * t_ms
                        / 7000.0f
                    )
                );
        }

        float value = pulseWave(
            phase,
            rr_ms,
            amplitude
        );

        if (modulation) {
            value +=
                18.0f
                * std::sin(
                    2.0f
                    * 3.1415926535f
                    * t_ms
                    / 9000.0f
                );
        }

        const ZeezDetectorEvent event =
            detector.update(
                static_cast<uint32_t>(i),
                static_cast<int64_t>(
                    t_ms * 1000.0f
                ),
                value,
                true
            );

        if (event.candidate) {
            ++candidate_count;
        }

        if (event.accepted) {
            ++accepted_count;

            if (event.rr_ms > 0) {
                rr_values.push_back(
                    static_cast<float>(
                        event.rr_ms
                    )
                );
            }
        }
    }

    if (rr_values.size() < 8) {
        std::cerr
            << "too few RR: "
            << rr_values.size()
            << "\n";
        return false;
    }

    for (
        size_t i = 1;
        i < rr_values.size();
        ++i
    ) {
        const float key =
            rr_values[i];

        size_t j = i;

        while (
            j > 0
            && rr_values[j - 1] > key
        ) {
            rr_values[j] =
                rr_values[j - 1];
            --j;
        }

        rr_values[j] = key;
    }

    const float median =
        rr_values[
            rr_values.size() / 2
        ];

    if (
        std::fabs(
            median - rr_ms
        ) > 35.0f
    ) {
        std::cerr
            << "RR mismatch: "
            << median
            << " vs "
            << rr_ms
            << "\n";
        return false;
    }

    const float hr =
        detector.currentHrBpm();

    if (
        hr < min_hr
        || hr > max_hr
    ) {
        std::cerr
            << "HR mismatch: "
            << hr
            << "\n";
        return false;
    }

    if (
        rr_ms > 500.0f
        && candidate_count
        <= accepted_count
    ) {
        std::cerr
            << "candidate competition not exercised\n";
        return false;
    }

    return true;
}

int main() {
    const bool resting =
        runCase(
            900.0f,
            20.0f,
            64.0f,
            70.0f,
            false
        );

    const bool drifting =
        runCase(
            820.0f,
            24.0f,
            68.0f,
            78.0f,
            true
        );

    const bool high_hr =
        runCase(
            333.0f,
            12.0f,
            168.0f,
            192.0f,
            false
        );

    return (
        resting
        && drifting
        && high_hr
    ) ? 0 : 1;
}
''',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-O2",
            "-I",
            str(lib),
            str(
                lib
                / "zeez_detector.cpp"
            ),
            str(harness),
            "-o",
            str(executable),
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, (
        result.stdout
        + "\n"
        + result.stderr
    )

    run = subprocess.run(
        [str(executable)],
        text=True,
        capture_output=True,
    )

    assert run.returncode == 0, (
        run.stdout
        + "\n"
        + run.stderr
    )
