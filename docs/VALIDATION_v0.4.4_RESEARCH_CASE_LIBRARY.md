# v0.4.4 Research Case Library + Inclusive Matching · Validation

## Automated regression

- `python -m compileall desktop/src`: PASS
- `pytest`: 135 passed
- `git diff --check`: PASS
- fresh v0.4.3 baseline + patch: `git apply --check` PASS, 135 tests passed

新增回归覆盖：

1. 约 12 分钟可形成 `PROVISIONAL` 参照，但仍不是 `MATURE`；
2. 正常连续采集到 15 分钟必须产生 `primary_conclusion`；
3. LIMITED 质量不改变同一身体数据的案例相似度，只降低可信程度；
4. 较慢与较快绝对起伏同时增强可以进入“起伏整体变强”；
5. 缺失特征返回 missing / NaN，不再伪装成“正好处于个人常态”；
6. 短时 INVALID 保留最近可靠用户结论；
7. 用户文案与新增研究事实继续禁止暴露工程术语。

## Real-session replay

Source: current uploaded `hrv_export.zip` / `hrv_windows.csv`.

- total HRV windows: 208
- mature frequency-ready windows: 184
- v0.4.3 exported hour state: 45 min `STABLE_NEUTRAL`, 14 min `DATA_UNSTABLE`
- v0.4.4 timeline points at/after 15 min: 55
- analyzable points at/after 15 min: 41
- analyzable points with a named rhythm conclusion: 41 / 41 (100%)
- first post-15-minute conclusion: 15.2 min, `STEADY_EVEN`, case similarity ~0.803, baseline `PROVISIONAL`
- mature-reference transition: 23.4 min; `RESONANCE_0P1` case similarity ~0.747
- last reliable conclusion before terminal quality loss: 64.1 min, `STEADY_EVEN`
- current 70.2 min result: `HELD`, `STEADY_EVEN`

This replay is a product-layer validation, not ECG ground truth. It does not establish that any research case is the user's psychological state.
