# v0.3.5 Patch：同极性相位分支

## 固件

- normal decision：1.06×RR → 1.40×RR；
- Candidate Pool：形态/时间权重 0.86/0.14；
- Winner：形态/时间权重 0.90/0.10；
- normal Winner 门：0.50；
- 第一 Rescue：phase 1.50、门 0.20；
- 波形 Rescue：phase 1.65；
- 保留 v0.3.4 独立相位跟踪与 Peak Complex。

## 桌面端

- 模板启动 Winner 分 ≥0.74；
- 普通 ±120 ms 搜索保留；
- 增加独立周期预测恢复；
- 增加 source-centered 半周期宽恢复；
- 大偏移恢复要求高模板相关 + 节律一致；
- 连续失配可在高分 Winner 上重新建模板；
- 导出 `timing_recovered`；
- UI 增加“相位恢复”计数。

## 协议

继续使用 v4，帧格式不变。
