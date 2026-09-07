# zeezPPG v0.3.1 动态心搏检测算法

## 目标

腕部 PPG 的主要难点包括：

- DC 基线漂移；
- 幅值随接触压力变化；
- 同一脉搏有肩峰 / 重搏成分；
- 主峰宽度变化；
- 个别周期显著变弱；
- 运动伪迹产生高斜率局部极值。

单一幅值阈值很难同时控制误检与漏检。

v0.3.0 将判断拆成“形态 + 时间上下文”。

## 1. 预处理

```text
raw
↓
25 ms EMA
↓
1.20 s baseline EMA
↓
raw_avg - baseline
↓
20 ms pulse EMA
```

最终 `filtered` 是有符号去基线 PPG。

检测器同时允许正局部极大值和负局部极小值，因此不依赖固定波形极性。

## 2. 环形缓冲区

### Signal / Slope

容量 320 点。

每次 push：

```text
移除最旧值对 sum / sumsq 的贡献
写入新值
加入新值贡献
移动 write_index
```

动态均值：

```text
mean = sum / N
```

动态标准差：

```text
std = sqrt(sumsq/N - mean²)
```

### RR

最近 9 个 Accepted RR。

使用中位数和 MAD，降低单次异常对周期预测的影响。

### Candidate Pool

最多 16 个局部极值。

一个心搏周期允许多个候选存在，最终通过综合评分竞争一个 Winner。

## 3. Candidate 形态特征

局部斜率发生符号变化时形成极值候选：

```text
+ slope → <=0 : 局部最大值
- slope → >=0 : 局部最小值
```

每个候选计算：

```text
amplitude_z
prominence_z
slope_z
curvature_z
```

分量经过 sigmoid 后组合：

```text
morphology =
  0.32 * amplitude
+ 0.32 * prominence
+ 0.24 * slope
+ 0.12 * curvature
```

该评分是工程算法分，不是概率。

## 4. 自相关周期预测

最近最多 256 个 filtered 点用于相关扫描。

搜索范围约：

```text
40–220 bpm
```

算法计算每个 lag 的归一化自相关。

### 谐波处理

严格选择全局最大相关峰容易得到：

```text
真实 333 ms
相关峰 333 / 666 / 999 ms 都很强
```

v0.3.0 在达到全局最大值 90% 的局部强峰中选择最早一个，
以捕获最早稳定重复的完整形状。

## 5. 节律锚点

Accepted RR 中位数与自相关周期共同形成 `expected_rr_ms`。

当自相关置信度高，且 Accepted RR 与波形周期明显分离时：

```text
优先 autocorrelation period
```

这可以阻断：

```text
错误 Winner
→ 错 RR
→ 错 expected RR
→ 下一周期继续选错
```

的正反馈。

## 5.1 同极性锁（v0.3.1）

第一个稳定 Winner 后锁定：

```text
locked_polarity = +1 或 -1
```

Candidate 层仍保留峰和谷；Accepted 层只允许同极性事件。
Rescue 同样服从该极性。

获得至少两个稳定同极性 RR 后，RR 中位数成为主节律锚点。
自相关只在与 RR 接近时参与轻度平滑。

## 6. 周期内竞争

建立节律后，一个周期不会看到 Candidate 就立即接受。

### 正常决策

约到达：

```text
1.06 × expected RR
```

时，在：

```text
0.55–1.38 × expected RR
```

范围内选综合评分最高的 Candidate。

综合评分：

```text
combined =
0.64 * morphology
+ 0.36 * timing
```

### Rescue 1

到达：

```text
1.35 × expected RR
```

后降低形态门，优先避免漏搏。

### Rescue 2

到达：

```text
1.58 × expected RR
```

仍没有候选时，直接在预测周期窗口内回看波形，寻找最显著极值。

Rescue 结果通过 Beat flag 标记，供后续分析和训练。

## 7. 心率

```text
最近 9 个 Accepted RR
→ median
→ 60000 / median_RR
```

Candidate 数量不会直接改变主心率。

## 8. CNN 接口

当前形态评分已经输出：

```text
detector_score
Candidate
Accepted score
Rescued
expected_rr
```

后续 CNN 可以只替换/增强 `morphology_score`，周期预测、Winner 选择、
RR/HRV 链无需修改。
