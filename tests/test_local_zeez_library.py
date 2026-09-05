from pathlib import Path


def test_zeezppg_is_project_local_and_cheez_dependency_removed():
    root = (
        Path(__file__)
        .resolve()
        .parents[1]
    )

    library = (
        root
        / "firmware"
        / "lib"
        / "zeezPPG"
        / "src"
    )

    for name in [
        "zeezPPG.h",
        "zeezPPG.cpp",
        "zeez_detector.h",
        "zeez_detector.cpp",
    ]:
        assert (library / name).is_file()

    platformio = (
        root
        / "firmware"
        / "platformio.ini"
    ).read_text(
        encoding="utf-8"
    )

    assert "CheezPPG" not in platformio
    assert not any(line.strip().startswith("lib_deps") for line in platformio.splitlines())
    assert "patch_cheezppg" not in platformio



def test_autocorrelation_is_incremental_not_burst_scan():
    root = (
        Path(__file__)
        .resolve()
        .parents[1]
    )

    header = (
        root
        / "firmware"
        / "lib"
        / "zeezPPG"
        / "src"
        / "zeez_detector.h"
    ).read_text(
        encoding="utf-8"
    )

    source = (
        root
        / "firmware"
        / "lib"
        / "zeezPPG"
        / "src"
        / "zeez_detector.cpp"
    ).read_text(
        encoding="utf-8"
    )

    assert "AUTOCORR_LAGS_PER_UPDATE = 4" in header
    assert "AUTOCORR_MAX_PAIRS_PER_LAG = 96" in header
    assert "computeAutocorrelationLag" in source

    # v0.3.1 的整块扫描入口必须彻底消失。
    assert "estimateAutocorrelationPeriod" not in source
