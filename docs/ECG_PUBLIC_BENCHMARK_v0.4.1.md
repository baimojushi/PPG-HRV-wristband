# v0.4.1 ECG / public-data interval benchmark

This framework validates the **PPG → beat → RR interval core** independently of the
consumer UI, research prototypes and firmware Accepted Beat output.

## Why this exists

Internal agreement between two PPG detectors is useful quality evidence, but it is not
an external truth source. For release decisions the interval core must also be compared
against simultaneous ECG/reference beats. The design follows the public PPG-beats
benchmarking principles without copying its code:

- ECG reference beats are obtained from two independent ECG QRS detectors; windows are
  scored only when the two ECG detectors agree. If a dataset supplies trusted beat
  annotations, those can be used directly instead.
- PPG and ECG beats are aligned for pulse transit delay before scoring.
- The default correctness tolerance is ±150 ms.
- For long recordings the ECG→PPG lag can be re-estimated in 300 s windows to tolerate
  slow clock drift.
- Report sensitivity, PPV and F1 for beat detection, plus RR MAE/p95/correlation and
  RMSSD/SDNN error. Execution time is reported as a percentage of signal duration.

These choices are consistent with the assessment approach described by Charlton et al.
(2022) and the MSPTDfast v2 benchmark. The local implementation is independently written.

## 1. Smoke test

From `desktop/`:

```bash
python -m hrv_app.benchmark synthetic --output benchmark_results/synthetic
```

This runs the exact production v0.4.1 interval core against a synthetic pulse train with
known reference beats and pulse delay. It is a regression smoke test, not a scientific
validation dataset.

## 2. Open BIDMC benchmark

BIDMC is open access and contains 53 synchronized 8-minute PPG and ECG recordings at
125 Hz. The framework can download the CSV recordings directly from PhysioNet and cache
them locally:

```bash
python -m hrv_app.benchmark bidmc --records 01-05 \
  --cache benchmark_data/bidmc \
  --output benchmark_results/bidmc_01_05
```

Full set:

```bash
python -m hrv_app.benchmark bidmc --records 01-53 \
  --cache benchmark_data/bidmc \
  --output benchmark_results/bidmc_all
```

BIDMC does **not** provide manual R-peak annotations in these CSV files, so the framework
creates an ECG reference consensus from two independent QRS paths and excludes low-
agreement ECG windows. The report therefore distinguishes `reference_coverage` from PPG
performance.

BIDMC source: https://physionet.org/content/bidmc/1.0.0/

## 3. Your synchronized wrist PPG + ECG experiment

The two CSV files may have different native sample rates. Both need a timestamp column on
the same clock/time unit. Fixed physiological pulse delay and slow drift are handled by
the alignment stage.

```bash
python -m hrv_app.benchmark csv-pair \
  --ppg wrist_ppg.csv --ppg-time time_s --ppg-value filtered \
  --ecg chest_ecg.csv --ecg-time time_s --ecg-value ecg \
  --record-id static_wear_001 \
  --output benchmark_results/static_wear_001
```

If your external ECG device exports R-peak annotations, package the synchronized signals
as NPZ with `ppg`, `ppg_fs` and `reference_beats_s`; the ECG waveform is then optional.

## 4. NPZ interchange

Required:

- `ppg`: 1-D PPG array
- `ppg_fs`: scalar Hz

And either:

- `reference_beats_s`: trusted beat times in seconds, or
- `ecg` plus `ecg_fs`

Run:

```bash
python -m hrv_app.benchmark npz record.npz --output benchmark_results/record
```

## Reports

Each run writes:

- `record_metrics.csv`: one row per recording
- `summary.json`: median / IQR aggregate results
- `details.json`: ECG quality windows, lag windows, production PPG detector evidence

Important fields:

- `reference_coverage`: fraction of the recording where ECG reference quality is accepted
- `sensitivity_percent`, `ppv_percent`, `f1_percent`
- `timing_mae_ms`, `timing_p95_ms` after ECG→PPG lag alignment
- `rr_mae_ms`, `rr_p95_ms`, `rr_correlation`
- `rmssd_abs_error_ms`, `sdnn_abs_error_ms`
- `realtime_ratio_percent`

No pass/fail scientific threshold is baked into the program. Thresholds must be calibrated
against the intended use case and datasets rather than guessed from one wrist recording.
For CI regression only, explicit gates can be supplied, e.g.:

```bash
python -m hrv_app.benchmark bidmc --records 01-05 \
  --fail-under-f1 95 --fail-over-rr-mae-ms 20
```

## Recommended validation ladder

1. Synthetic smoke regression on every code change.
2. BIDMC 01-53 as the first open, mostly high-quality ECG/PPG baseline.
3. Add MIMIC PERform / CapnoBase for clinical diversity.
4. Add WESAD and PPG-DaLiA for motion / daily-life stress.
5. Most importantly, record the actual wrist device simultaneously with a chest ECG or
   ECG reference device, including static wear, paced breathing, loose/tight contact,
   mild hand movement and deliberate sensor clipping.

The public-data result and the hardware synchronized result answer different questions;
neither should replace the other.

## References

- Charlton PH et al. Detecting beats in the photoplethysmogram: benchmarking open-source
  algorithms. Physiological Measurement, 2022. https://pmc.ncbi.nlm.nih.gov/articles/PMC9393905/
- Charlton PH et al. The MSPTDfast photoplethysmography beat detection algorithm: design,
  benchmarking, and open-source distribution. https://pmc.ncbi.nlm.nih.gov/articles/PMC11894679/
- PPG-beats performance assessment documentation:
  https://ppg-beats.readthedocs.io/en/latest/toolbox/performance_assessment/
- BIDMC PPG and Respiration Dataset:
  https://physionet.org/content/bidmc/1.0.0/
