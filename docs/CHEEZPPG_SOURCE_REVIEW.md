# CheezPPG 源码审查结论

## v1.0.2

公开接口包含：

```text
setWearThreshold()
checkSampleInterval()
ppgProcess()
getPpgisWear()
getPpgPeak()
getRawPPG()
getAvgPPG()
getFilterPPG()
getPpgHr()
getPpgHrv()
```

官方源码没有 `setPeakThresholdFactor()`。

峰值检测使用 18 点局部统计窗口，固定阈值因子等价于 9。

## 项目兼容

项目添加一个极小补丁：

```text
9 × local_std
↓
peakThresholdFactor × local_std
```

默认仍为 9，项目初始化时设置为 11。

## v1.1.x

v1.1.x 峰值机制已经更换，没有与旧 `11.0` 一一等价的公开接口。
该版本留作未来单独 A/B 实验，不与本次开发平台迁移混在同一变量中。
