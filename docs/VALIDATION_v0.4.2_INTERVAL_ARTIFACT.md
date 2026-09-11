# v0.4.2 Interval Artifact Validation

## 验证目标

本报告验证 v0.4.2 是否实现了计划中的结构性修复，而不是通过继续调 gate 数字让 UI 看起来更稳定。

验证包含：

- 单元/回归测试；
- Python compileall；
- 2026-09-10 两次长时间腕带实测的 **v0.4.1 formal PPG Beat 时间线离线 A/B replay**。

重要限制：两次腕带记录没有同步 ECG。因此 A/B replay 能验证“新序列层是否正确处理已经观察到的 RR 结构、是否消除旧 cleaner 的 reject cascade”，不能证明每一颗 PPG Beat 对 ECG R-peak 的绝对准确度。

## 自动测试

最终打包前执行：

```text
python -m compileall -q desktop/src desktop/run_ui.py desktop/analyze_csv.py
pytest -q
```

并在全新基线副本上执行 patch apply + 完整测试，防止只在开发工作树中通过。

## 针对性回归

v0.4.2 新测试覆盖：

- 双 detector 都支持时，`336.004 + 407.998 ≈ 744.002 ms` 仍能被 interval layer 判断为 extra-peak split；
- `1296.004 ms` 可按附近节律拆成 2 个 corrected NN；
- long-short compensating pair 保持总时长；
- 连续真实速率改变不会生成 reject cascade；
- 已解决 artifact 不会触发“连续未解决异常” gate；
- corrected artifact 比例较高本身不再 hard-gate time HRV；
- sequence resolver 能从长间期中重新取回实际存在的 single-detector candidate；
- 成熟 5 分钟频率窗口保留边界 anchor；
- buffering frequency row 不进入 research baseline；
- LIMITED evidence 不再把 similarity 上限压在 0.70 门槛以下；
- 历史 research timeline 不因未来数据加入而改变过去分数；
- A-neutral-A 不再被摘要成 A→A；
- analysis snapshot/history 时间不倒退；
- artifact provenance 保留 raw RR、配对时间和 corrected RR。

## 实测 A/B：20260910_135448

输入不是重新跑 raw PPG detector，而是直接使用该会话 v0.4.1 `beat_provenance.csv` 中已经提交的 formal PPG Beat 时间。这种做法有意隔离 **同一条 Beat 时间线下旧 cleaner vs v0.4.2 interval layer** 的差异。

### 全会话 interval quality

| 指标 | v0.4.1 | v0.4.2 |
|---|---:|---:|
| raw RR | 2831 | 2831 |
| accepted NN | 2816 | 2830 |
| detected artifact ratio | 0.530% | 0.035% |
| unresolved ratio | 0.530% | 0.035% |
| max consecutive artifact | 6 | 1 |
| max consecutive unresolved | 旧版等同 max artifact | 1 |

旧 cleaner 在记录末段形成了 `local_outlier` reject cascade；滚动 60-RR 窗口中最大连续 unresolved 为 6，并有 61 个窗口超过旧 `>2` 连续异常门。v0.4.2 最大连续 unresolved 为 1，超过 2 的窗口为 0。

### 约 20 秒时域重算

为隔离 interval 行为，该 replay 固定 Transport/Contact 为可用，仅保留 Beat 本身已有的 local-clipped evidence。

| 状态 | v0.4.1 | v0.4.2 |
|---|---:|---:|
| VALID | 86 | 95 |
| LIMITED | 7 | 0 |
| INVALID | 17 | 15 |
| 快照总数 | 110 | 110 |

新版本消除了由 unresolved cascade 造成的假 INVALID/LIMITED；末段剩余 INVALID 主要来自真实存在的“正式心搏峰附近削底/饱和”，没有为了提高通过率把独立质量证据一起放开。

## 实测 A/B：20260910_152745

### 全会话 interval quality

| 指标 | v0.4.1 | v0.4.2 |
|---|---:|---:|
| raw RR | 2496 | 2496 |
| accepted NN | 2487 | 2492 |
| unresolved ratio | 0.240% | 0.040% |
| max artifact run | 2 | 2 |
| max unresolved run | 2 | 1 |
| resolved artifact ratio | — | 0.120% |

v0.4.2 在原始 formal Beat 上得到以下关键结构决策：

| 会话时间 | raw RR | local reference | 结果 | corrected NN |
|---|---:|---:|---|---:|
| 14.7776 min | 336.004 ms | 756.000 ms | extra peak：第一段 | 不单独产生 NN |
| 14.7844 min | 407.998 ms | 756.000 ms | 与前一段合并 | 744.002 ms |
| 14.9339 min | 1296.004 ms | 620.001 ms | 疑似漏 1 搏，拆 2 段 | 648.002 × 2 |
| 30.4997 min | 1208.000 ms | 936.001 ms | 孤立异常，证据不足以修复 | unresolved |

前两项即本次实测审查中抓到的 P0 反例。它们在 v0.4.1 都具有 dual-detector 支持；v0.4.2 证明 detector agreement 已不再被当成最终真值。

### 约 20 秒时域重算

| 状态 | v0.4.1 | v0.4.2 |
|---|---:|---:|
| VALID | 79 | 83 |
| LIMITED | 11 | 7 |
| INVALID | 8 | 8 |
| 快照总数 | 98 | 98 |

约 15.28 min 的窗口在 v0.4.1 中存在连续 artifact=2；v0.4.2 中这对异常已被结构层解决，`max_consecutive_unresolved=0`。该窗口仍然 INVALID，因为正式 Beat 峰附近 clipping 约 15%，超过独立的 peak-local 质量条件。这个结果符合目标：

> 修复错误的 interval gate，但不把真实波形质量问题一起隐藏。

## 判定

这两次 replay 支持以下结论：

1. v0.4.1 的 dual-detector consensus 是有价值的波形证据，但不足以成为正式 NN 的最终判据；
2. v0.4.2 能在 dual-detector 都同意的情况下识别典型 extra/missed structural error；
3. 新局部参考不再因为单个拒绝事件形成长串 self-sustaining local-outlier cascade；
4. resolved structural artifact 与 unresolved evidence 已经在质量门中分离；
5. local clipping、Transport、SpectralReliability 仍保持独立，不通过“放宽所有 gate”换取更漂亮的状态数。

## 下一阶段验证

下一轮真实实测重点查看：

```text
interval_candidate_trace.csv
interval_artifact_trace.csv
beats_cleaned.csv
nn_intervals.csv
```

若出现长 RR，优先确认其内部是否存在被拒 single-detector candidate；若出现短短 RR 对，确认 extra-peak 结构是否得到正确合并。

同步 ECG / 公共 ECG-reference benchmark 仍是 release-level accuracy 的必要条件。没有 ECG reference 时，不把本报告中的 structural replay 结果包装成 sensitivity / PPV / F1。
