#pragma once

#include <Arduino.h>
#include "data_types.h"

// 诊断计数只使用 32 位读写。
// ESP32 对齐的 32 位访问是原子的，V1 不额外引入跨核互斥，避免采集路径再次被锁阻塞。
class Diagnostics {
public:
    void onSampleDrop();
    void onBeatDrop();
    void onMetricDrop();

    void observeSampleQueueDepth(uint16_t depth);

    DiagnosticFrame snapshot(int64_t now_us, uint16_t current_depth) const;

private:
    volatile uint32_t sample_drop_count_ = 0;
    volatile uint32_t beat_drop_count_ = 0;
    volatile uint32_t metric_drop_count_ = 0;

    volatile uint16_t sample_queue_high_water_ = 0;
};
