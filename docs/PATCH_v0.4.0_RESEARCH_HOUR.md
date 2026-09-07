# v0.3.9 → v0.4.0 Patch

## 新增模块

```text
desktop/src/hrv_app/literature_registry.py
desktop/src/hrv_app/research_prototypes.py
```

## 新增能力

```text
研究文献事实注册表
方括号数字 UI 超链接
个人近期稳健基线
Q0–Q6 研究状态机
6 个急性研究原型
T0 长期身份参照门
过去一小时阶段模型
过去一小时状态时间轴
状态持续 / 转场统计
研究原型分数图
质量不足时自动暂停原型解释
```

## 导出

新增：

```text
research_prototype_snapshot.json
hour_experience.json
research_prototype_table.json
literature_sources.json
research_state_timeline.csv
```

`summary.json` 同时加入：

```text
research_prototypes
hour_experience
```

## 固件

没有修改。

协议继续 v4。

不需要重新烧录 ESP32。
