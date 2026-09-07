#pragma once

#include <Arduino.h>
#include "config.h"
#include "data_types.h"

// ESP32 端轻量 RMSSD 累积器。
// 目的：
// 1. 保留当前项目“每 20 秒输出一次 RMSSD”的行为；
// 2. 在进入 RMSSD 前先剔除明显不合理的 RR；
// 3. 不在采集任务中执行任何频域或重型统计计算。
class LegacyHrvAccumulator {
public:
    void pushRR(uint16_t rr_ms, bool wear);
    MetricFrame compute(int64_t now_us) const;

private:
    struct RRItem {
        uint16_t rr_ms = 0;
        bool valid = false;
    };

    RRItem items_[HRV_WINDOW_RR_COUNT] = {};
    size_t count_ = 0;
    size_t write_index_ = 0;

    const RRItem &itemFromOldest(size_t logical_index) const;
};
