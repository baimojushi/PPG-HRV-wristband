# v0.3.4 Patch：独立节律相位 + HRV 模板时间标志点

基线：v0.3.3。

## 固件修改

- 同极性 Candidate 增加 Peak Complex 合并；
- 新增独立 `predicted_beat_t_us`；
- Candidate timing score 不再直接由上一搏 Accepted 时间起算；
- 单搏时间误差只用小增益校正节律相位；
- Rescue 改为围绕独立预测目标搜索；
- 协议仍为 v4，无线上帧字段变化。

## 桌面端修改

- 新增 `TemplateFiducialRefiner`；
- 固件 Beat 与 HRV Beat 分开保存；
- HRV 时间标志点使用整段 PPG 模板互相关；
- 低质量相关不改写时间轴；
- 新增 Beat Timing Quality；
- UI 灰虚线显示固件 Winner，绿色显示 HRV 统一 fiducial；
- 导出新增 `beats_refined.csv`。

## 延迟

桌面 HRV 细化默认等待约 400 ms 波形上下文。

固件实时心率和 Candidate 检测不增加这部分延迟。
