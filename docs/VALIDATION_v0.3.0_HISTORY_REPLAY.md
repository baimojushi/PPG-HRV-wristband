# v0.3.0 动态 zeezPPG：历史 PPG 回放验收

三份历史 CSV 的旧 Peak / HR 数值不参与新的 Accepted Beat 判定。
旧 `HR>0` 仅用于重建历史文件的佩戴状态；Accepted Beat 由 filtered PPG 重新计算。

重点检查多周期漏搏：`RR > 1.8 × 当前文件 RR 中位数`。

## record.csv

- Accepted HR：80.645 bpm
- RR 数：1949
- RR 中位数：872.0 ms
- RR P95：1032.0 ms
- RR 最大值：1216.0 ms
- 多周期长 RR 数：0
- 时域状态：INVALID
- 正式 RMSSD：None
- Candidate RMSSD：74.777 ms
- 异常搏比例：11.67%
- SQI：55.0%
- 频域状态：INVALID

## 娟第一次冥想.csv

- Accepted HR：69.444 bpm
- RR 数：1923
- RR 中位数：832.0 ms
- RR P95：896.0 ms
- RR 最大值：968.0 ms
- 多周期长 RR 数：0
- 时域状态：INVALID
- 正式 RMSSD：None
- Candidate RMSSD：25.427 ms
- 异常搏比例：0.00%
- SQI：55.0%
- 频域状态：INVALID

## 状态不佳时读教科书.csv

- Accepted HR：68.182 bpm
- RR 数：793
- RR 中位数：792.0 ms
- RR P95：912.0 ms
- RR 最大值：1400.0 ms
- 多周期长 RR 数：0
- 时域状态：INVALID
- 正式 RMSSD：None
- Candidate RMSSD：87.897 ms
- 异常搏比例：6.67%
- SQI：92.3%
- 频域状态：INVALID

## 解释

三份历史记录均没有出现 `>1.8×中位 RR` 的连续多周期漏搏间隔。
历史文件的 SQI 和 HRV 有效性仍按原始数据质量门判断；
低 SQI 文件继续保持 INVALID，不用“检测器看起来更好”覆盖数据质量问题。

历史回放用于回归检测算法稳定性，最终参数仍需新 v0.3.0 固件的实时 Sample/Beat 数据做 A/B。