# v0.3.1 同极性锁修复

## 根因

v0.3.0 对局部最大值和局部最小值采用对称形态评分。
实测中两者都可能成为 Winner，造成峰/谷交替双计数。

## 修改

- 新增 `locked_polarity`；
- 第一个稳定 Winner 锁定极性；
- `selectBestCandidate()` 过滤反极性 Candidate；
- `waveformRescue()` 过滤反极性极值；
- 两个稳定同极性 RR 后，RR 中位数成为主节律锚点；
- 正常 Candidate 窗口：0.72–1.55 × expected RR；
- 超时候选窗口：0.72–2.20 × expected RR；
- 波形 Rescue：phase >= 1.70；
- 分析导出新增 `samples_debug.csv` / `beats_raw.csv`；
- 协议保持 v4。
