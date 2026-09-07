from pathlib import Path
import shutil
import subprocess

import pytest


def test_zeezppg_arduino_wrapper_compiles_with_stub(tmp_path: Path):
    compiler = shutil.which("g++")

    if compiler is None:
        pytest.skip("当前环境没有 g++")

    project = Path(__file__).resolve().parents[1]
    lib = (
        project
        / "firmware"
        / "lib"
        / "zeezPPG"
        / "src"
    )

    stub = tmp_path / "Arduino.h"
    stub.write_text(
        '''
#pragma once
#include <stdint.h>
#include <stddef.h>

static inline uint32_t micros() {
    static uint32_t value = 0;
    value += 8000;
    return value;
}

static inline int analogRead(uint8_t) {
    return 300;
}
''',
        encoding="utf-8",
    )

    harness = tmp_path / "wrapper.cpp"
    harness.write_text(
        '''
#include "zeezPPG.h"

int main() {
    zeezPPG ppg(32, 125);
    ppg.setWearThreshold(1);
    ppg.setPeakThresholdFactor(11.0f);

    ppg.ppgProcess(1, 8000);

    zeezPPGBeat beat;
    (void)ppg.popAcceptedBeat(beat);

    return 0;
}
''',
        encoding="utf-8",
    )

    executable = tmp_path / "wrapper"

    result = subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-O2",
            "-I",
            str(tmp_path),
            "-I",
            str(lib),
            str(lib / "zeez_detector.cpp"),
            str(lib / "zeezPPG.cpp"),
            str(harness),
            "-o",
            str(executable),
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, (
        result.stdout + "\n" + result.stderr
    )
