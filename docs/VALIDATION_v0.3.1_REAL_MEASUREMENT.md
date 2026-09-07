# v0.3.1 实测回归：峰/谷双极性误计数

## 实测证据

界面：

```text
Candidate 49 / 12 s
Accepted 33 / 12 s
预测 RR 464 ms
接受 HR 172 bpm
```

导出：

```text
RR 数                       177
RR 中位数                   364.0 ms
相邻两个 RR 之和中位数       721.0 ms
```

隔一个 Accepted 取一个：

```text
序列 A RR 中位数             725.1 ms
序列 A 对应 HR               82.7 bpm
序列 A Winner 平均分         0.724

序列 B RR 中位数             720.0 ms
序列 B 对应 HR               83.3 bpm
序列 B Winner 平均分         0.651
```

约 79.5% 的相邻二元组中，A 序列 Winner 分更高。

这与截图中绿色 Accepted 在主峰和谷值附近交替出现一致，根因为：
**双极性 Candidate 同时参与 Winner 竞争。**

## v0.3.1

- 第一个稳定 Winner 锁定极性；
- 后续 Candidate 竞争只接受同极性；
- Rescue 同样服从极性锁；
- 两个稳定同极性 RR 后优先使用 RR 中位数；
- 导出增加 `samples_debug.csv` / `beats_raw.csv`。
