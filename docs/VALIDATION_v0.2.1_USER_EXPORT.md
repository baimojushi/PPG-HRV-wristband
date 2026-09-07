# v0.2.1 Patch：用户导出 Beat 数据回放

输入：用户本次上传的 `beats_cleaned.csv`。

本报告只验证事件级 RR/NN 清洗。为了隔离 PPG SQI 的影响，
时域测试人为设置 `SQI=95%`；即使在这个有利条件下，异常搏质量门仍会生效。

## 清洗结果

- 原始 RR 数：1094
- accepted：769
- false_peak：94
- false_peak_merged：94
- missed_beat_repaired：3
- hard_outlier：62
- local_outlier：72

## 最终 60 搏时域质量门

- valid：False
- status：INVALID
- accepted NN：49
- detected_artifact_ratio：0.1833
- unresolved_suspect_ratio：0.0833
- max_consecutive_artifacts：3
- candidate RMSSD：82.214 ms
- validity_reason：异常搏 18.3% > 5.0%；未解决异常 8.3% > 2.0%；连续异常搏 3 > 1

正式 UI/导出在 `valid=false` 时会把 `rmssd_ms` 输出为 `null/--`，
`candidate_rmssd_ms` 只留在 JSON 调试字段。

## 951 / 639 / 311 / 824 目标片段

- 原始：[951.0, 639.0, 311.0, 824.0]
- 状态：['accepted', 'false_peak', 'false_peak_merged', 'accepted']
- NN：[951.0, 0.0, 950.0, 824.0]
