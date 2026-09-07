#include "diagnostics.h"

void Diagnostics::onSampleDrop() {
    ++sample_drop_count_;
}

void Diagnostics::onBeatDrop() {
    ++beat_drop_count_;
}

void Diagnostics::onMetricDrop() {
    ++metric_drop_count_;
}

void Diagnostics::observeSampleQueueDepth(uint16_t depth) {
    if (depth > sample_queue_high_water_) {
        sample_queue_high_water_ = depth;
    }
}

DiagnosticFrame Diagnostics::snapshot(int64_t now_us, uint16_t current_depth) const {
    DiagnosticFrame frame;
    frame.t_us = now_us;

    frame.sample_drop_count = sample_drop_count_;
    frame.beat_drop_count = beat_drop_count_;
    frame.metric_drop_count = metric_drop_count_;

    frame.sample_queue_depth = current_depth;
    frame.sample_queue_high_water = sample_queue_high_water_;
    return frame;
}
