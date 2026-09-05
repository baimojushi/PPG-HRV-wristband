# 原代码短板 → 当前修复

| 原代码短板 | 当前实现 |
|---|---|
| PPG 采样与 `Serial.println / BTSerial.println` 串联 | Core 1 采集、Core 0 传输 |
| 每 8 ms 大量 `String` 动态拼接 | 固定 `char[] + snprintf` |
| PPG 对象被采样与 HRV 任务共享 | PPG 对象由采集任务独占 |
| 互斥锁失败后仍可能输出旧 getter 值 | 只有真实完成的 `ppgProcess()` 才生成 SampleFrame |
| RR 依赖库内部缓冲且缺少独立真实时基 | 峰值 `esp_timer_get_time()` 直接计算 RR |
| 没有明确丢样计数 | sample / beat / metric drop counter |
| 没有连续样本编号 | `seq` |
| 没有微秒采样时间戳 | `t_us` |
| RMSSD 前没有异常搏处理 | 固件硬过滤 + PC 局部 MAD 清洗 |
| 一个异常 RR 能显著抬高 RMSSD | 异常搏不参与相邻 RMSSD 差值 |
| 每个样本重复发送 20 秒才更新的 HRV 历史 | Sample / Beat / Metric 三类帧分离 |
| “0” 同时表示无效值和真实数值 | valid / confidence / reason 分离 |
| 计算出 HRV 就默认可信 | SQI + 分层可信度 |
| 手动导出 CSV 再计算频域 | PC 实时 Welch / Lomb / SPWVD |
| 工程依赖 Arduino IDE 本机库 | PlatformIO 工程化，并显式纳入定制库目录 |
