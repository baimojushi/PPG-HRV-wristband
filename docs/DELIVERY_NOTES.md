# 交付说明

> 本文件保留 v0.2.x 演化记录；当前运行实现以最末尾的 v0.3.0 和 README 为准。

## 已完成

### ESP32 / PlatformIO

- Arduino IDE 单文件迁移为 VS Code + PlatformIO；
- 保留 125 Hz、GPIO32、Wear=1、PeakFactor=11.0；
- `zeezPPG` 对象只允许采集任务访问；
- 采集任务与 USB / 蓝牙传输完全解耦；
- 样本增加 `seq + t_us`；
- RR 由相邻峰值的真实微秒时间戳计算；
- FreeRTOS 队列溢出显式计数；
- 原始信号增加削底 / 饱和质量标志；
- 保留每 20 秒轻量 RMSSD，并在其前增加 RR 硬异常过滤；
- 蓝牙初始化失败时 USB 仍可继续输出。

### Python HRV 分析

- RR → NN 两级清洗：
  - 300–2000 ms 硬异常；
  - 局部中位数 + MAD 难异常；
- 时域：
  - Mean NN
  - Mean HR
  - RMSSD
  - SDNN
  - pNN50
  - Artifact ratio
- 频域：
  - 5 分钟窗口
  - 4 Hz PCHIP 重采样
  - Welch 功率谱
  - VLF / LF / HF / LF-HF
  - Lomb–Scargle 形状交叉验证
- 时频域：
  - 平滑伪 Wigner-Ville 分布（SPWVD）
  - VLF(t) / LF(t) / HF(t) / LF-HF(t)
- SQI：
  - 佩戴覆盖
  - PPG 削底
  - PPG 饱和
  - 样本序号缺口
  - 采样时基抖动
- 可信度：
  - signal
  - beat
  - time_hrv
  - frequency
  - overall
  - reason flags

### UI

- PySide6 + PyQtGraph；
- C 端心理健康 / 艺术疗愈视觉方向；
- 首页只突出心率、通过质量门的 RMSSD、数据质量 SQI；
- PPG 实时波形；
- RMSSD 趋势；
- 专业页 Welch PSD；
- 专业页 SPWVD；
- 频域不足 5 分钟时显示积累状态；
- 历史 CSV 后台加载；
- 串口后台线程；
- 实时原始会话自动落盘；
- 清洗后 Beat / HRV 窗口 / JSON 摘要导出。

## v0.2.0 CheezPPG 依赖调整

- 删除手工 `zeezPPG` 占位依赖；
- 固定官方 CheezPPG v1.0.2；
- 增加 PlatformIO PRE 自动补丁；
- 保留 `setPeakThresholdFactor(11.0)`；
- 补丁脚本幂等；
- 官方源码结构不匹配时主动终止构建。

首次固件构建需要联网下载官方依赖。


## v0.2.1 Patch

本版本增加：

- BeatTimelineCleaner：伪峰合并、漏搏修复、未解决异常跳过；
- 时域 / 频域强制质量门；
- 协议 v3：`@ + CRC16 + 自动重同步`；
- SQI + VALID/LIMITED/INVALID；
- RMSSD 近似 bootstrap 95% 区间；
- Total Power / VLF / LF / HF / LFnu / HFnu / LF-HF / HF-LF；
- 会话级频带统计；
- 同一冻结快照导出。

本次用户 Beat 导出回放见：

`docs/VALIDATION_v0.2.1_USER_EXPORT.md`


## v0.2.3 Peak Event Gate

- 修复 `raw peak 0→1 == BeatFrame` 的根因；
- raw peak 只启动候选；
- Accepted Beat 使用滤波 PPG 局部最大值时间戳；
- 同一波形多次 threshold rising 合并；
- 主心率切换到 Accepted RR 中位数；
- 库 HR 单独保留 Debug；
- UI 增加 Candidate / Accepted 双层 0/1；
- 历史 CSV 使用同一事件门；
- 新增约 180 bpm / 220 bpm 高心率防二分频测试；
- 协议仍为 v3。


## v0.3.0 zeezPPG 重写

- 完整 `zeezPPG` 源码进入项目本地库；
- 固件取消 CheezPPG 下载依赖和自动补丁；
- 信号 / 斜率 / RR 使用固定环形缓冲区；
- 加入动态幅值、突出度、斜率和曲率评分；
- 加入自相关周期预测和谐波保护；
- 一个周期允许多个 Candidate，最终选一个 Winner；
- 加入周期超时 Rescue Search；
- Sample/Beat 导出保存检测分数与预测 RR；
- 协议升级 v4，桌面端兼容 v2/v3；
- CNN 保留数据和评分接口，当前未启用；
- HRV 清洗与 SQI 质量门继续作为第二层保护。


## v0.3.1 同极性锁

- 根据实测 `Accepted 33 / 12 s` 与 `RR median 364 ms` 定位峰/谷交替计数；
- 第一个稳定 Winner 锁定局部极值极性；
- 常规 Candidate 竞争与 Rescue 全部过滤反极性极值；
- 两个稳定同极性 RR 后，RR 中位数成为主节律锚点；
- 分析导出新增 `samples_debug.csv` / `beats_raw.csv`；
- 协议保持 v4。


## v0.3.2 采样时基与时频三级质量

- 实测定位每 16 samples 一次约 66 ms 长停顿；
- 完整自相关扫描改为固定预算增量扫描；
- SQI 新增有效采样率 / p95 / 超时比例并对严重时基异常硬封顶；
- 时域新增 LIMITED 输出；
- 频域新增 Welch/Lomb + 双插值互证；
- SPWVD 可在受限频域通过硬门后运行；
- UI 直接显示实时有效采样率；
- 协议保持 v4。


## v0.3.3 稳健频谱互证

- 固件保持 v0.3.2，不需要重新烧录；
- 原始 Welch/Lomb 逐频点 Pearson 改为 Debug；
- 新增约 0.02 Hz 平滑后的谱形相关；
- 新增 VLF/LF/HF 频带分布一致性；
- 正式门使用二者加权的稳健一致性；
- Welch 绝对功率与频带积分完全不变；
- 对五种缓峰 fiducial 做离线 A/B，未发现足够净收益，因此不修改 RR 时间戳；
- CNN 当前保持 NO-GO，原因见 `CNN_ENGINEERING_ROI_v0.3.3.md`。
