# v0.4.1 Benchmark Framework Validation

- Python `compileall`: PASS
- Full pytest suite: **112 passed**
- Synthetic 90 s end-to-end smoke: **F1 100%**, RR MAE **2.95 ms**, RR p95 **6.38 ms**, RR correlation **0.9948**.
- Synthetic ECG-only reference mode (two independent QRS detectors): covered clean windows and reproduced the same PPG beat timeline in regression tests.
- BIDMC CSV parser and official PhysioNet column mapping (`Time [s]`, `PLETH`, `II`) are unit-tested.

The artifact runtime does not have outbound network access, so a full 53-record BIDMC download/run was **not** claimed here. The CLI is wired to the verified PhysioNet open CSV path and is intended to be run on the development machine with network access.

This framework is a validation harness, not a new HRV quality gate. It intentionally imposes no default scientific pass/fail threshold. Release thresholds should be selected only after observing multiple external datasets and synchronized wrist-PPG/ECG recordings.
