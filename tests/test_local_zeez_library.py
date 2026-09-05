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
