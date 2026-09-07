# v0.4.0 研究原型匹配状态机

## 1. 定位

这一层不修改 PPG 检测、RR 清洗和 HRV 数值。

输入：

```text
HR
RMSSD
VLF / LF / HF
HFnu / LF/HF
中位频率
0.06–0.10 Hz THM 子带
0.075–0.11 Hz 共振子带
LF 主峰频率与突出度
数据质量
过去一小时趋势
```

输出：

```text
质量状态
个人近期基线状态
研究原型匹配度
CANDIDATE / ACTIVE / EXITING
过去一小时状态分布与转场
研究来源编号
```

匹配度是工程相似度，不是疾病概率、冥想深度概率或身份概率。

## 2. 总状态机

| 代码 | 状态 | 触发 |
|---|---|---|
| `Q0_BUFFERING` | 数据积累 | 第一个 5 分钟频域窗口尚未完成 |
| `Q1_DATA_UNSTABLE` | 数据不稳 | 正式频域或统一质量门失败 |
| `Q2_BASELINE_BUILDING` | 个人基线建立 | 频域已经可用，但稳定参照窗口不足 |
| `Q3_ANALYZABLE` | 可分析 | 数据质量与个人近期基线满足 |
| `Q4_STATE_CANDIDATE` | 原型候选 | 某研究原型匹配度 ≥0.70，尚未满足持续门 |
| `Q5_STATE_ACTIVE` | 原型持续 | 连续至少 2 个指标更新窗口 ≥0.70 |
| `Q6_STATE_EXITING` | 原型退出 | 前期达到候选/持续，之后连续 2 个窗口 <0.45 |

`RESONANCE_0P1` 属于波形结构型原型，可以在个人基线完成前先进入 `CANDIDATE`。

## 3. 个人近期基线

基线不使用固定人群常模。

从当前会话中：

```text
排除最近 60 s
保留 VALID / LIMITED 稳定窗口
每约 120 s 取一个参照点
至少 3 个参照点
覆盖至少 4 min
```

各特征使用：

```text
median
+
1.4826 × MAD
```

计算稳健 z*。

功率类特征先取对数，再进入个人基线。

## 4. 急性研究原型

### 4.1 INWARD_QUIET

**内部名称**

```text
内向安静 / 高频增强型
```

**测试状态描述**

静止、注意向内时，相对个人近期稳定基线：

```text
HR ↓
RMSSD ↑
HF ↑
LF/HF ↓
```

**工程匹配**

```text
HF z* 上升          32%
RMSSD z* 上升       26%
HR z* 下降          22%
LF/HF z* 下降       20%
```

**研究统计参照**

- 10 名有 Zen 禅修经验者与 10 名无禅修经验对照；
- 内向注意冥想中，经验组 LF/HF 和 LF 标准化功率下降，HF 标准化功率上升；
- 同时观察到较规则的心率振荡。

来源：

```text
[1] Shr-Da Wu, Pei-Chen Lo
Inward-attention meditation increases parasympathetic activity:
a study based on heart rate variability
Biomedical Research, 2008
https://pubmed.ncbi.nlm.nih.gov/18997439/
```

补充参照：

- 10 名长期 Theravada 练习者，平均约 8 年；
- Vipassana 相对静息 HF 增加，LF/HF 下降。

```text
[5] Ido Amihai, Maria Kozhevnikov
Arousal vs. Relaxation: A Comparison of the Neurophysiological and
Cognitive Correlates of Vajrayana and Theravada Meditative Practices
PLOS ONE, 2014
```

---

### 4.2 RESONANCE_0P1

**内部名称**

```text
0.1 Hz 共振样
```

**测试状态描述**

```text
LF 主峰约 0.075–0.11 Hz
主峰相对 LF 背景突出
0.075–0.11 Hz 占 LF+HF 较高
连续窗口主峰频率稳定
```

**工程匹配**

```text
主峰频率接近 0.095 Hz       36%
主峰 / 背景突出度           27%
共振子带功率占比             25%
最近约 3 min 主峰稳定度       12%
```

**研究统计参照**

- 10 名有经验冥想者，4 女 6 男，平均年龄 42 岁；
- 依次完成 relaxation response、breath of fire、segmented breathing；
- relaxation response 与 segmented breathing 中出现约 0.05–0.10 Hz 高振幅心率振荡；
- 同时心率与呼吸相干性相对基线显著增强；
- breath of fire 则表现为平均心率升高和相干下降。

```text
[2] C-K Peng et al.
Heart rate dynamics during three forms of meditation
International Journal of Cardiology, 2004
https://pubmed.ncbi.nlm.nih.gov/15159033/
```

时频方法补充：

- 19 名不同 Zazen 经验水平练习者；
- 研究同时使用频域分析和连续小波变换；
- 其中 4 个特殊个案同时记录呼吸；
- 研究观察到呼吸性心律调制随经验水平改变。

```text
[6] Caroline Peressutti et al.
Heart rate dynamics in different levels of Zen meditation
International Journal of Cardiology, 2010
```

---

### 4.3 PHASED_VIPASSANA

**内部名称**

```text
分阶段频谱组织 / Vipassana样
```

**测试状态描述**

过去约 12–24 分钟出现三段式结构：

```text
早段：LF / HF 较低
中段：LF 与 HF 共同增强
后段：再次回落
```

中段 LF/HF 同时作为辅助结构。

**工程匹配**

把最近最长 24 分钟有效历史分为三段，比较：

```text
中段 LF / 两侧 LF
中段 HF / 两侧 HF
中段 LF/HF / 两侧 LF/HF
```

**研究统计参照**

- 10 名男性有经验 Vipassana 冥想者；
- 年龄 20–61 岁；
- 至少 2 年规律练习，平均 7.5 年，平均每周约 15 小时；
- 30 分钟结构化冥想：
  - Anapana 10 min
  - Vipassana 15 min
  - Metta 5 min
- LF 与 HF 在 Anapana 阶段下降，Vipassana 阶段增加，Metta 阶段再次下降；
- Vipassana 阶段 LF/HF 的增加更明显。

```text
[4] Luis Carlos Delgado-Pastor et al.
Mindfulness (Vipassana) meditation: effects on P3b event-related
potential and heart rate variability
International Journal of Psychophysiology, 2013
https://pubmed.ncbi.nlm.nih.gov/23892096/
```

---

### 4.4 TRAINED_VIPASSANA_SHIFT

**内部名称**

```text
HF增强 + THM下降训练样
```

**测试状态描述**

相对个人近期稳定基线：

```text
HFnu ↑
0.06–0.10 Hz THM 功率 ↓
LF 可同步轻度下降
```

**工程匹配**

```text
HFnu z* 上升                  48%
THM z* 下降                   42%
LF z* 下降                    10%
```

**研究统计参照**

- 36 名参与者；
- 10 天密集 Vipassana retreat 前后重复测试；
- 每次比较 5 分钟静息与 5 分钟冥想；
- retreat 前，冥想主要表现为 lnHF 增加；
- retreat 后，冥想出现 HF n.u. 增加，同时 THM 下降。

```text
[3] Jonathan R Krygier et al.
Mindfulness meditation, well-being, and heart rate variability:
a preliminary investigation into the impact of intensive Vipassana meditation
International Journal of Psychophysiology, 2013
https://pubmed.ncbi.nlm.nih.gov/23797150/
```

---

### 4.5 AROUSAL_MEDITATION

**内部名称**

```text
高唤醒冥想样
```

**测试状态描述**

数据质量稳定，同时相对个人基线：

```text
HF ↓
HR 没有明显减慢
RMSSD 没有同步上升
```

**工程匹配**

```text
HF z* 下降               52%
HR 非减速                28%
RMSSD 非上升             20%
```

**研究统计参照**

Study 1：

- 10 名长期 Theravada 练习者，平均 8 年；
- 9 名长期 Vajrayana 练习者，平均 7.4 年；
- Theravada 组来自泰国 Yannawa Temple；
- Vajrayana 组来自尼泊尔 Shechen Monastery；
- Theravada Vipassana 的 HF 相对静息增加，LF/HF 下降；
- Vajrayana 的 Deity 和 Rig-pa 则观察到 HF 下降的不同模式。

```text
[5] Ido Amihai, Maria Kozhevnikov
Arousal vs. Relaxation: A Comparison of the Neurophysiological and
Cognitive Correlates of Vajrayana and Theravada Meditative Practices
PLOS ONE, 2014
https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0102990
```

---

### 4.6 SLOW_RECOVERY_VLF

**内部名称**

```text
VLF慢恢复尾迹
```

**测试状态描述**

当前：

```text
HF ≈ 个人基线
LF/HF ≈ 个人基线
HR ≈ 个人基线
VLF 仍明显偏低
```

同时要求过去 3–30 分钟存在：

```text
HF下降
VLF下降
LF/HF上升
```

至少一种较明显的前序激活结构。

**研究统计参照**

- 19 名健康年轻受试者；
- 静息 10 min；
- Stroop 任务 20 min；
- 任务后继续静息恢复 120 min；
- HF 与 VLF 在任务中下降、LF/HF 上升；
- 任务结束后 HF 与 LF/HF 很快回到基线；
- VLF 在恢复期仍持续低于静息水平。

```text
[7] Harunobu Usui, Yusuke Nishida
The very low-frequency band of heart rate variability represents
the slow recovery component after a mental stress task
PLOS ONE, 2017
https://pubmed.ncbi.nlm.nih.gov/28806776/
```

## 5. 长期身份参照层

v0.4.0 固定输出：

```text
T0_TRAIT_UNKNOWN
```

不会自动判断：

```text
初学冥想者
长期冥想者
高阶修行者
运动员
```

因为当前产品只有单次会话基线。

长期层需要：

```text
至少 7–14 天
至少 10 次稳定会话
同一测量条件
```

再研究：

```text
ENTRY_LATENCY
STATE_STABILITY
STATE_DURATION
REPRODUCIBILITY
FLEXIBILITY
```

研究参照之一：

- Heart Chan 长期组 27 人；
- 平均练习 9 年，范围 1–27 年；
- 每次课程 90 min；
- 论文使用课前/课后及一个月重复测量观察 HR、HRV 和频域指标。

```text
[8] Kang-Ming Chang, Miao-Tien Wu Chueh, Yi-Jung Lai
Meditation Practice Improves Short-Term Changes in Heart Rate Variability
International Journal of Environmental Research and Public Health, 2020
https://pmc.ncbi.nlm.nih.gov/articles/PMC7142551/
```

## 6. UI 来源格式

研究事实后统一输出：

```html
<a href="URL">[1]</a> Author — Literature title
```

因此：

```text
[数字]
```

在 Qt UI 中本身就是超链接。

作者、文献名和受试者身份同时保留，避免用户看到一个无上下文的数字引用。
