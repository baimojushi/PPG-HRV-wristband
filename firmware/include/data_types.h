#pragma once

#include <Arduino.h>

// 样本质量 / 状态标志。
// 采用位标志，后续可以在不破坏协议的情况下增加新状态。
enum SampleFlags : uint16_t {
    SAMPLE_FLAG_NONE = 0,
    SAMPLE_FLAG_WEAR = 1 << 0,
    SAMPLE_FLAG_CLIP_LOW = 1 << 1,
    SAMPLE_FLAG_CLIP_HIGH = 1 << 2,
    SAMPLE_FLAG_QUEUE_PRESSURE = 1 << 3,
};

// RR / 心搏状态标志。
enum BeatFlags : uint16_t {
    BEAT_FLAG_NONE = 0,
    BEAT_FLAG_WEAR = 1 << 0,
    BEAT_FLAG_FIRST = 1 << 1,
    BEAT_FLAG_RR_HARD_INVALID = 1 << 2,
    // 该 Beat 已经过 zeezPPG 的周期内候选竞争，被选为最终心搏。
    BEAT_FLAG_ADAPTIVE_ACCEPTED = 1 << 3,

    // 旧名称保留为二进制兼容别名。
    BEAT_FLAG_PEAK_GATED = BEAT_FLAG_ADAPTIVE_ACCEPTED,
    // 周期预测超时后由 rescue search 找回的心搏。
    BEAT_FLAG_RESCUED = 1 << 4,
};

// 125 Hz 原始采样帧。
// t_us 直接来自 ESP32 高精度计时器，后续不再依赖“样本序号 × 8 ms”估算时基。
struct SampleFrame {
    uint32_t seq = 0;
    int64_t t_us = 0;

    int16_t raw = 0;
    int16_t avg = 0;
    int16_t filtered = 0;

    // v0.3.0：peak 字段表示“动态形态候选脉冲”，不是最终心搏。
    uint8_t peak = 0;

    // 连续形态活跃度 0~1，仅用于 Debug / 日后模型训练。
    float detector_score = 0.0f;

    // 动态周期预测，尚未建立时为 0。
    float expected_rr_ms = 0.0f;

    // 当前 Accepted RR 中位数心率。
    float hr_bpm = 0.0f;

    uint16_t flags = SAMPLE_FLAG_NONE;
};

// 每个 zeezPPG 周期 winner 生成一个心搏帧。
// rr_ms 使用真实局部极值时间戳差；候选局部极值不会直接生成 BeatFrame。
struct BeatFrame {
    uint32_t seq = 0;
    int64_t t_us = 0;

    uint16_t rr_ms = 0;
    float hr_bpm = 0.0f;

    // 周期内 winner 的综合评分 0~1。
    float score = 0.0f;

    uint16_t flags = BEAT_FLAG_NONE;
};

// ESP32 端保留一个轻量 RMSSD 结果，便于脱离桌面端时调试。
// 桌面端的 NN 清洗 + 时频域分析仍是最终结果来源。
struct MetricFrame {
    int64_t t_us = 0;

    float rmssd_ms = 0.0f;
    uint16_t valid_rr_count = 0;
    float artifact_ratio = 1.0f;
    uint8_t valid = 0;
};

// 运行诊断帧。
// 这些计数让“传输阻塞”和“采样异常”可以在日志里被明确观测，而不是悄悄污染数据。
struct DiagnosticFrame {
    int64_t t_us = 0;

    uint32_t sample_drop_count = 0;
    uint32_t beat_drop_count = 0;
    uint32_t metric_drop_count = 0;

    uint16_t sample_queue_depth = 0;
    uint16_t sample_queue_high_water = 0;
};
