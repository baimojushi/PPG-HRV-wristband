#include "legacy_hrv.h"
#include <math.h>

void LegacyHrvAccumulator::pushRR(uint16_t rr_ms, bool wear) {
    RRItem item;
    item.rr_ms = rr_ms;

    // 只在固件端做非常保守的硬异常过滤。
    // 局部中位数 / MAD 难异常清洗由 Python 端负责，避免增加 ESP32 实时负担。
    item.valid =
        wear &&
        rr_ms >= RR_HARD_MIN_MS &&
        rr_ms <= RR_HARD_MAX_MS;

    items_[write_index_] = item;
    write_index_ = (write_index_ + 1) % HRV_WINDOW_RR_COUNT;

    if (count_ < HRV_WINDOW_RR_COUNT) {
        ++count_;
    }
}

const LegacyHrvAccumulator::RRItem &
LegacyHrvAccumulator::itemFromOldest(size_t logical_index) const {
    // 环形缓冲区尚未填满时，数据从 0 开始。
    if (count_ < HRV_WINDOW_RR_COUNT) {
        return items_[logical_index];
    }

    // 环形缓冲区填满后，write_index_ 指向下一次覆盖位置，也就是当前最旧位置。
    const size_t index = (write_index_ + logical_index) % HRV_WINDOW_RR_COUNT;
    return items_[index];
}

MetricFrame LegacyHrvAccumulator::compute(int64_t now_us) const {
    MetricFrame out;
    out.t_us = now_us;

    if (count_ == 0) {
        return out;
    }

    uint16_t valid_rr_count = 0;
    uint16_t invalid_rr_count = 0;

    double diff_square_sum = 0.0;
    uint16_t valid_diff_count = 0;

    // RMSSD 只允许“相邻两项都有效”的 RR 对参与计算。
    // 这样剔除一个伪峰后，不会把伪峰前后两个 RR 强行跨接成一个新差值。
    for (size_t i = 0; i < count_; ++i) {
        const RRItem &current = itemFromOldest(i);

        if (current.valid) {
            ++valid_rr_count;
        } else {
            ++invalid_rr_count;
        }

        if (i + 1 >= count_) {
            continue;
        }

        const RRItem &next = itemFromOldest(i + 1);
        if (!current.valid || !next.valid) {
            continue;
        }

        const int32_t diff =
            static_cast<int32_t>(next.rr_ms) -
            static_cast<int32_t>(current.rr_ms);

        diff_square_sum += static_cast<double>(diff) * static_cast<double>(diff);
        ++valid_diff_count;
    }

    out.valid_rr_count = valid_rr_count;
    out.artifact_ratio =
        static_cast<float>(invalid_rr_count) /
        static_cast<float>(count_);

    if (valid_rr_count < HRV_MIN_VALID_RR_COUNT || valid_diff_count < 4) {
        return out;
    }

    out.rmssd_ms =
        static_cast<float>(sqrt(diff_square_sum / static_cast<double>(valid_diff_count)));
    out.valid = 1;
    return out;
}
