# v0.4.6 日常佩戴采样契约验证

## 自动回归

完整测试集：

```text
147 passed
```

新增覆盖：

- `seq +4 / 32 ms` 稳定蓝牙流识别为 `stride=4`，TransportQuality=VALID；
- 31.25 Hz 接收流仍能反推出约 125 Hz 设备源采样时钟；
- 规则抽样不再产生 75% 假丢包和 24 ms 假抖动；
- 蓝牙流中真正少一个转发帧时，`+8` 只计 1 个缺帧；
- 旧的 `seq +1 / 偶发 66 ms` 采样停顿仍然 INVALID；
- 31.25 Hz 规则抽样 PPG 会在 interval core 前带限重采样到约 125 Hz 分析网格；
- 约 10% 已解决修复负担输出 LIMITED，而不是 INVALID；
- 约 20% 修复负担仍然 INVALID。

## 真实波形 A/B

使用当前源码包中已有的 125 Hz 实测 `samples_debug.csv`，截取约 120 秒连续片段，并人为保留每 4 点中的 1 点来复现蓝牙传输。然后分别经过当前 v0.4.6 同一套预处理、双检测器和 consensus：

```text
原始 125 Hz：14993 samples，181 consensus beats
模拟蓝牙流： 3749 samples，识别输入 31.25 Hz，分析网格 125 Hz，182 consensus beats
匹配到原始 beat：181
匹配 beat 绝对时间差中位数：约 0.001 ms
匹配 beat 绝对时间差 p95：约 7.997 ms
原始 consensus RR RMSSD：198.744 ms
模拟蓝牙 consensus RR RMSSD：201.470 ms
```

该片段本身包含较大的逐搏变化，因此这里不把 RMSSD 数值当作生理真值；验证目标是确认同一条实测波形经过 4 倍规则抽样后，Beat 数量、峰位和 RR 差分不再被 32 ms 网格系统性破坏。

## 结构检查

```text
python -m compileall desktop/src tests
pytest -q
```

均通过。

## 固件

`firmware/` 未修改。当前固件已经明确存在：

```cpp
PPG_SAMPLE_RATE_HZ = 125
BT_SAMPLE_DECIMATION = 4
```

本次修复发生在桌面端对该既有采样契约的识别与分析，因此 **无需重新烧录 ESP32**。
