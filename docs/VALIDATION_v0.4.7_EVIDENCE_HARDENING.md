# v0.4.7 验证记录：Beat 证据链与重采样审计

## 静态检查

- `python -m compileall -q desktop/src tests`：通过。
- `python -m pytest --collect-only -q`：153 tests collected。

## 全测试集合（分组执行）

为了避免单次运行时间限制，31 个测试模块按回归组执行；所有组累计 **153 passed**，没有失败。覆盖 Python HRV/频域/研究状态/UI 源码约束、Protocol、Interval Core、RR Cleaner，以及 3 个 C++ host/stub 编译测试。

## v0.4.7 新增边界测试

`tests/test_evidence_hardening_v047.py` 共 6 项：

1. 干净双检测器 Beat：Timing Quality 维持高值；
2. 单检测器 + 序列救援 + 较高时间不确定度：正式 Timing Quality 明显下降；
3. Firmware 相位偏移约 330 ms：Firmware Alignment 降级，但正式波形 Timing Quality 不被错误拉低；
4. Firmware Beat 未匹配：显式记录 `firmware_unmatched`，不作为正式时间线惩罚；
5. 规则 31.25 Hz、`seq +4` 蓝牙流：确认 4:1 重采样契约，输入时钟与回投影误差均为有限值；
6. 相邻 20 秒窗口：从低 Firmware 匹配 / 大相位偏移过渡到高匹配 / 小偏移时，匹配率、offset p95 和 Timing Quality 的 delta 都能显式暴露。

## 解释边界

本补丁增加的是“证据真实性与可审计性”，不是把 Firmware Beat 重新升格为 HRV ground truth。`firmware_alignment_*` 只能证明固件事件与桌面正式 Beat 的相位关系；`resample_backprojection_*` 只能量化变换链对输入波形的改写量。若要回答绝对 Beat 准确度，仍需要同步 ECG / 人工标注等外部参考。
