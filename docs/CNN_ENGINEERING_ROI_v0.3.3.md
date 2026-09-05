# v0.3.3 一维卷积神经网络工程性价比评估

## 结论

当前阶段 **不建议把一维卷积神经网络加入实时心搏主链**。

原因来自本次实测数据：

```text
实际采样率            125.00 Hz
采样 p95 抖动        0.0040 ms
时间线未解决异常      0.402%
有效 NN               99.598%
```

心搏检测已经非常干净。

v0.3.2 滚动窗口的 Welch/Lomb 原始逐频点一致性仍可降到：

```text
52.0%
```

但同一批 RR 的 VLF/LF/HF 频带分布一致性最低仍有：

```text
86.9%
```

v0.3.3 使用多尺度互证后，稳健一致性最低：

```text
81.5%
```

因此这次瓶颈主要位于 **频谱估计器比较尺度**，不在“Candidate 是不是真心搏”的分类能力。

CNN 无法解决 Welch 与 Lomb–Scargle 的有限窗泄漏、频率 bin 轻微错位问题。

---

## 1. 如果未来引入 CNN，算力不是主要障碍

建议只让 CNN 做：

```text
Candidate 形态评分器
```

保持：

```text
极性锁
周期预测
Candidate 竞争
Rescue
RR 清洗
HRV 质量门
```

仍由可解释算法完成。

一个足够小的候选模型可以是：

```text
输入
128 samples × 2 channels

Channel 0 = robust-normalized PPG
Channel 1 = first derivative

Conv1D 2→8, kernel=5
ReLU
MaxPool /2
Conv1D 8→12, kernel=5
ReLU
Global Average Pool
Dense 12→8
Dense 8→1
```

模型参数：

```text
Conv1        80 weights + 8 bias
Conv2       480 weights + 12 bias
Dense1       96 weights + 8 bias
Dense2        8 weights + 1 bias
--------------------------------
总参数       693
```

INT8 权重本体约：

```text
693 bytes
```

单次推理主要乘加：

```text
Conv1        ≈10,240 MAC
Conv2        ≈30,720 MAC
Dense        ≈104 MAC
--------------------------------
合计         ≈41k MAC / candidate
```

即使 Candidate 达到 8 次/秒：

```text
≈328k MAC/s
```

模型计算量本身对 ESP32 属于较小规模。

实际部署还会增加：

- 运行时；
- 算子工作区；
- 量化代码；
- 模型版本管理。

这些开销需要在目标板实测。

---

## 2. 真正昂贵的是训练数据和验证

现有：

```text
candidate=1
accepted beat
rejected candidate
detector_score
expected_rr
```

可以自动构建**弱标签数据集**。

这些标签来自当前算法自身。

直接拿来训练 CNN 会产生循环：

```text
旧算法判断
→ 作为训练标签
→ CNN 学会旧算法判断
```

对于真正需要 CNN 解决的难例：

- 缓峰；
- 平顶峰；
- 接触压力变化；
- 运动尖峰；
- 重搏成分；
- 弱搏；
- 波形极性变化；

仍需要独立标签。

最优标签来源：

```text
同步 ECG R 峰
```

次优：

```text
人工复核的 PPG beat fiducial
```

没有独立标签时，CNN 的表面准确率没有足够工程意义。

---

## 3. 当前确定性算法与 CNN 的收益比较

### 当前确定性方案

优点：

- 固件源码小；
- 可逐事件解释；
- 可用现有 CSV 完整复盘；
- 参数变化容易做 A/B；
- 不需要训练数据；
- 当前实测时间线异常仅约 0.40%。

当前主要剩余问题：

```text
频谱互证方法
```

v0.3.3 已直接针对该问题修复。

### Tiny 1D CNN

潜在收益：

- 复杂形态下比手工特征更容易学习非线性边界；
- 有机会降低运动伪峰和缓峰漏检；
- 可以利用当前 Candidate Pool 只在候选点运行。

工程代价：

- 需要独立标注；
- 需要训练/验证/量化流水线；
- 需要跨用户、佩戴松紧、运动状态验证；
- 模型版本与固件版本需要绑定；
- 模型误判的 Debug 成本明显高于当前形态评分；
- 无法改善频域估计器自身的不一致。

---

## 4. Go / No-Go 条件

当前建议：

```text
NO-GO：直接把 CNN 放进实时固件
GO：继续积累训练数据和难负例
```

只有在新实测中反复出现以下情况，再进入 CNN 实装：

1. 采样时基稳定；
2. 同极性锁正常；
3. RR 清洗前仍持续出现明显误搏/漏搏；
4. 问题可以追溯到 Candidate 形态分类；
5. 确定性动态特征已无法在泛化和精度间继续兼顾。

CNN A/B 至少应证明：

```text
难噪声片段误搏/漏搏下降 ≥30%
清洁片段不明显退化
Rescue 比例下降
未解决 RR 比例下降
跨会话验证仍成立
```

并在目标 ESP32 上实测：

```text
推理时间
堆内存
任务抖动
采样率
```

其中任何一项使 125 Hz 采样时基退化，都不接受。

---

## 5. 推荐路线

### v0.3.3

```text
不加入 CNN
```

先使用：

- 稳健 Welch/Lomb 互证；
- VLF/LF/HF 分布互证；
- 当前动态 zeezPPG；
- 原始逐频点相关继续 Debug。

### 后续数据阶段

自动保存：

```text
candidate 前后约 1 s PPG
一阶差分
detector_score
expected_rr
Accepted / Rejected
人工或 ECG 标签
```

### CNN 实验阶段

CNN 只替换：

```text
morphology_score
```

最终：

```text
combined_score =
CNN morphology
+ timing context
```

这样即使 CNN 实验失败，也不用重新修改 RR/HRV 架构。

---

## 工程性价比评级

当前：

```text
计算可行性        高
实现难度          中
训练数据成本      高
验证成本          高
对当前问题收益    低
总体性价比        低~中
```

当积累独立标注的高噪声数据后：

```text
总体性价比可升至  中~高
```
