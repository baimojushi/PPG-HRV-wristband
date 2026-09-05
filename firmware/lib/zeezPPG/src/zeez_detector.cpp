#include "zeez_detector.h"

#include <math.h>

// ============================================================================
// RunningRing
// ============================================================================

void ZeezAdaptiveDetector::RunningRing::clear() {
    write_index = 0;
    count = 0;
    sum = 0.0;
    sum_sq = 0.0;

    for (size_t i = 0; i < SIGNAL_RING_CAPACITY; ++i) {
        values[i] = 0.0f;
    }
}

void ZeezAdaptiveDetector::RunningRing::push(float value) {
    if (count == SIGNAL_RING_CAPACITY) {
        const float old = values[write_index];
        sum -= old;
        sum_sq -= static_cast<double>(old) * old;
    } else {
        ++count;
    }

    values[write_index] = value;
    sum += value;
    sum_sq += static_cast<double>(value) * value;

    write_index = (write_index + 1) % SIGNAL_RING_CAPACITY;
}

float ZeezAdaptiveDetector::RunningRing::mean() const {
    if (count == 0) {
        return 0.0f;
    }

    return static_cast<float>(sum / static_cast<double>(count));
}

float ZeezAdaptiveDetector::RunningRing::stddev(float floor_value) const {
    if (count < 2) {
        return floor_value;
    }

    const double n = static_cast<double>(count);
    const double mean_value = sum / n;
    double variance = (sum_sq / n) - mean_value * mean_value;

    if (variance < 0.0) {
        variance = 0.0;
    }

    const float result = static_cast<float>(sqrt(variance));
    return result > floor_value ? result : floor_value;
}

float ZeezAdaptiveDetector::RunningRing::minLast(size_t n) const {
    if (count == 0) {
        return 0.0f;
    }

    if (n > count) {
        n = count;
    }

    float result = 0.0f;
    bool initialized = false;

    for (size_t offset = 0; offset < n; ++offset) {
        const size_t index =
            (write_index + SIGNAL_RING_CAPACITY - 1 - offset)
            % SIGNAL_RING_CAPACITY;

        const float value = values[index];

        if (!initialized || value < result) {
            result = value;
            initialized = true;
        }
    }

    return result;
}

float ZeezAdaptiveDetector::RunningRing::maxLast(size_t n) const {
    if (count == 0) {
        return 0.0f;
    }

    if (n > count) {
        n = count;
    }

    float result = 0.0f;
    bool initialized = false;

    for (size_t offset = 0; offset < n; ++offset) {
        const size_t index =
            (write_index + SIGNAL_RING_CAPACITY - 1 - offset)
            % SIGNAL_RING_CAPACITY;

        const float value = values[index];

        if (!initialized || value > result) {
            result = value;
            initialized = true;
        }
    }

    return result;
}

float ZeezAdaptiveDetector::RunningRing::maxAbsLast(size_t n) const {
    if (count == 0) {
        return 0.0f;
    }

    if (n > count) {
        n = count;
    }

    float result = 0.0f;

    for (size_t offset = 0; offset < n; ++offset) {
        const size_t index =
            (write_index + SIGNAL_RING_CAPACITY - 1 - offset)
            % SIGNAL_RING_CAPACITY;

        const float value = fabsf(values[index]);

        if (value > result) {
            result = value;
        }
    }

    return result;
}

// ============================================================================
// SignalRing
// ============================================================================

void ZeezAdaptiveDetector::SignalRing::clear() {
    write_index = 0;
    count = 0;

    for (size_t i = 0; i < SIGNAL_RING_CAPACITY; ++i) {
        points[i] = SignalPoint{};
    }
}

void ZeezAdaptiveDetector::SignalRing::push(
    const SignalPoint &point
) {
    points[write_index] = point;
    write_index = (write_index + 1) % SIGNAL_RING_CAPACITY;

    if (count < SIGNAL_RING_CAPACITY) {
        ++count;
    }
}

bool ZeezAdaptiveDetector::SignalRing::getNewest(
    size_t offset,
    SignalPoint &out
) const {
    if (offset >= count) {
        return false;
    }

    const size_t index =
        (write_index + SIGNAL_RING_CAPACITY - 1 - offset)
        % SIGNAL_RING_CAPACITY;

    out = points[index];
    return true;
}

// ============================================================================
// RR ring
// ============================================================================

void ZeezAdaptiveDetector::RrRing::clear() {
    write_index = 0;
    count = 0;

    for (size_t i = 0; i < RR_RING_CAPACITY; ++i) {
        values[i] = 0;
    }
}

void ZeezAdaptiveDetector::RrRing::push(uint16_t rr_ms) {
    if (rr_ms == 0) {
        return;
    }

    values[write_index] = rr_ms;
    write_index = (write_index + 1) % RR_RING_CAPACITY;

    if (count < RR_RING_CAPACITY) {
        ++count;
    }
}

float ZeezAdaptiveDetector::RrRing::median() const {
    if (count == 0) {
        return 0.0f;
    }

    uint16_t temp[RR_RING_CAPACITY] = {};

    for (size_t i = 0; i < count; ++i) {
        temp[i] = values[i];
    }

    for (size_t i = 1; i < count; ++i) {
        const uint16_t key = temp[i];
        size_t j = i;

        while (j > 0 && temp[j - 1] > key) {
            temp[j] = temp[j - 1];
            --j;
        }

        temp[j] = key;
    }

    if (count % 2 == 1) {
        return static_cast<float>(temp[count / 2]);
    }

    return 0.5f * static_cast<float>(
        temp[count / 2 - 1] + temp[count / 2]
    );
}

float ZeezAdaptiveDetector::RrRing::mad() const {
    if (count == 0) {
        return 0.0f;
    }

    const float center = median();
    float deviations[RR_RING_CAPACITY] = {};

    for (size_t i = 0; i < count; ++i) {
        deviations[i] = fabsf(
            static_cast<float>(values[i]) - center
        );
    }

    for (size_t i = 1; i < count; ++i) {
        const float key = deviations[i];
        size_t j = i;

        while (
            j > 0
            && deviations[j - 1] > key
        ) {
            deviations[j] = deviations[j - 1];
            --j;
        }

        deviations[j] = key;
    }

    if (count % 2 == 1) {
        return deviations[count / 2];
    }

    return 0.5f * (
        deviations[count / 2 - 1]
        + deviations[count / 2]
    );
}

// ============================================================================
// Detector
// ============================================================================

ZeezAdaptiveDetector::ZeezAdaptiveDetector(
    uint16_t sample_rate_hz
)
    : sample_rate_hz_(sample_rate_hz),
      sample_period_ms_(
          1000.0f
          / static_cast<float>(sample_rate_hz)
      ) {
    reset();
}

void ZeezAdaptiveDetector::reset() {
    signal_stats_.clear();
    slope_stats_.clear();
    signal_ring_.clear();
    rr_ring_.clear();

    candidate_pool_count_ = 0;

    has_previous_ = false;
    previous_value_ = 0.0f;
    previous_slope_ = 0.0f;
    previous_seq_ = 0;
    previous_t_us_ = 0;

    last_accepted_t_us_ = 0;
    last_accepted_seq_ = 0;
    predicted_beat_t_us_ = 0;
    last_phase_error_ms_ = 0.0f;
    locked_polarity_ = 0;

    expected_rr_ms_ = 0.0f;
    autocorr_rr_ms_ = 0.0f;
    autocorr_confidence_ = 0.0f;

    autocorr_scan_min_lag_ = 0;
    autocorr_scan_max_lag_ = 0;
    autocorr_scan_lag_ = 0;
    autocorr_scan_active_ = false;

    for (
        size_t i = 0;
        i < AUTOCORR_CORR_CAPACITY;
        ++i
    ) {
        autocorr_scan_values_[i] = 0.0f;
        autocorr_scan_valid_[i] = false;
    }

    current_hr_bpm_ = 0.0f;

    candidate_count_total_ = 0;
    accepted_count_total_ = 0;
    rescue_count_total_ = 0;

    // reset 不改变用户已经设置的兼容灵敏度。
}

void ZeezAdaptiveDetector::setLegacyPeakFactor(float factor) {
    if (!isfinite(factor) || factor <= 0.0f) {
        return;
    }

    legacy_peak_factor_ = factor;

    // 早期 11.0 作为中性点。
    // 更大的 factor 稍微提高门槛，更小的 factor 稍微降低门槛；
    // 限幅避免一个旧参数重新主宰整个非线性检测器。
    float scale = factor / 11.0f;

    if (scale < 0.78f) {
        scale = 0.78f;
    }
    if (scale > 1.28f) {
        scale = 1.28f;
    }

    score_threshold_scale_ = scale;
}

float ZeezAdaptiveDetector::sigmoid(float x) const {
    if (x > 8.0f) {
        return 0.9997f;
    }
    if (x < -8.0f) {
        return 0.0003f;
    }

    return 1.0f / (1.0f + expf(-x));
}

float ZeezAdaptiveDetector::clamp01(float value) const {
    if (value < 0.0f) {
        return 0.0f;
    }
    if (value > 1.0f) {
        return 1.0f;
    }
    return value;
}

float ZeezAdaptiveDetector::currentSignalScore(
    float value,
    float slope
) const {
    if (
        signal_stats_.count < 32
        || slope_stats_.count < 32
    ) {
        return 0.0f;
    }

    const float signal_std =
        signal_stats_.stddev(1.0f);
    const float slope_std =
        slope_stats_.stddev(0.20f);

    const float amplitude_z =
        fabsf(value - signal_stats_.mean())
        / signal_std;

    const float slope_z =
        fabsf(slope)
        / slope_std;

    // 连续显示用的“形态活跃度”：
    // 只用于 Debug，不直接等价于候选或心搏概率。
    return clamp01(
        0.60f * sigmoid((amplitude_z - 0.60f) * 1.4f)
        + 0.40f * sigmoid((slope_z - 0.60f) * 1.2f)
    );
}

bool ZeezAdaptiveDetector::detectLocalExtremum(
    ZeezCandidateFeatures &candidate
) const {
    if (
        !has_previous_
        || signal_stats_.count < 48
        || slope_stats_.count < 48
    ) {
        return false;
    }

    // previous_slope_ 是“前一个采样点处的斜率”，
    // 当前 slope 已经在 update() 中计算。
    SignalPoint current;
    if (!signal_ring_.getNewest(0, current)) {
        return false;
    }

    const float current_slope = current.slope;

    const bool is_maximum =
        previous_slope_ > 0.0f
        && current_slope <= 0.0f;

    const bool is_minimum =
        previous_slope_ < 0.0f
        && current_slope >= 0.0f;

    if (!is_maximum && !is_minimum) {
        return false;
    }

    // 局部极值实际位于 previous sample。
    candidate.seq = previous_seq_;
    candidate.t_us = previous_t_us_;
    candidate.value = previous_value_;
    candidate.polarity = is_maximum ? 1 : -1;

    candidate.morphology_score =
        morphologyScore(candidate);

    // 候选门刻意设得较宽。
    // 真正抑制假峰的主力是“周期内竞争”，而不是再造一个硬阈值。
    return candidate.morphology_score >= (0.20f * score_threshold_scale_);
}

float ZeezAdaptiveDetector::morphologyScore(
    ZeezCandidateFeatures &candidate
) const {
    const float signal_mean =
        signal_stats_.mean();
    const float signal_std =
        signal_stats_.stddev(1.0f);
    const float slope_std =
        slope_stats_.stddev(0.20f);

    const size_t prominence_window = static_cast<size_t>(
        0.28f * static_cast<float>(sample_rate_hz_)
    );

    const size_t slope_window = static_cast<size_t>(
        0.14f * static_cast<float>(sample_rate_hz_)
    );

    const float local_min =
        signal_stats_.minLast(prominence_window);
    const float local_max =
        signal_stats_.maxLast(prominence_window);

    float prominence = 0.0f;

    if (candidate.polarity > 0) {
        prominence = candidate.value - local_min;
    } else {
        prominence = local_max - candidate.value;
    }

    const float max_abs_slope =
        slope_stats_.maxAbsLast(slope_window);

    const float curvature =
        fabsf(previous_slope_);

    candidate.amplitude_z =
        fabsf(candidate.value - signal_mean)
        / signal_std;

    candidate.prominence_z =
        prominence / signal_std;

    candidate.slope_z =
        max_abs_slope / slope_std;

    candidate.curvature_z =
        curvature / slope_std;

    const float amplitude_score =
        sigmoid(
            (candidate.amplitude_z - 0.55f)
            * 1.45f
        );

    const float prominence_score =
        sigmoid(
            (candidate.prominence_z - 0.70f)
            * 1.35f
        );

    const float slope_score =
        sigmoid(
            (candidate.slope_z - 0.75f)
            * 1.20f
        );

    const float curvature_score =
        sigmoid(
            (candidate.curvature_z - 0.15f)
            * 1.00f
        );

    // 这里故意采用非线性分量组合，而不是单一阈值。
    // 任何一项偏弱都不会立刻“判死刑”，周期上下文还能把它救回来。
    const float score =
        0.32f * amplitude_score
        + 0.32f * prominence_score
        + 0.24f * slope_score
        + 0.12f * curvature_score;

    return clamp01(score);
}

float ZeezAdaptiveDetector::phaseForTime(
    int64_t t_us
) const {
    if (
        expected_rr_ms_ <= 0.0f
    ) {
        return 0.0f;
    }

    if (predicted_beat_t_us_ != 0) {
        // 1.0 表示独立节律预测的当前目标心搏。
        const float error_ms =
            static_cast<float>(
                t_us - predicted_beat_t_us_
            ) / 1000.0f;

        return
            1.0f
            + error_ms / expected_rr_ms_;
    }

    if (last_accepted_t_us_ != 0) {
        const float delta_ms =
            static_cast<float>(
                t_us - last_accepted_t_us_
            ) / 1000.0f;

        return delta_ms / expected_rr_ms_;
    }

    return 0.0f;
}

float ZeezAdaptiveDetector::timingScore(
    int64_t candidate_t_us
) const {
    if (
        expected_rr_ms_ <= 0.0f
        || (
            predicted_beat_t_us_ == 0
            && last_accepted_t_us_ == 0
        )
    ) {
        return 0.50f;
    }

    const float phase =
        phaseForTime(
            candidate_t_us
        );

    const float sigma = 0.24f;
    const float z = (phase - 1.0f) / sigma;

    return expf(-0.5f * z * z);
}

float ZeezAdaptiveDetector::candidateClusterWindowMs() const {
    if (expected_rr_ms_ <= 0.0f) {
        return 120.0f;
    }

    float window =
        expected_rr_ms_
        * CANDIDATE_CLUSTER_RR_RATIO;

    if (window < CANDIDATE_CLUSTER_MIN_MS) {
        window = CANDIDATE_CLUSTER_MIN_MS;
    }

    if (window > CANDIDATE_CLUSTER_MAX_MS) {
        window = CANDIDATE_CLUSTER_MAX_MS;
    }

    return window;
}

bool ZeezAdaptiveDetector::shouldReplaceClusterRepresentative(
    const ZeezCandidateFeatures &current,
    const ZeezCandidateFeatures &incoming
) const {
    // 同极性宽峰内部优先保留真正的幅值极值。
    // morphology 只在幅值非常接近时作第二裁判。
    const float value_margin = 0.5f;

    if (incoming.polarity > 0) {
        if (incoming.value > current.value + value_margin) {
            return true;
        }

        if (
            fabsf(incoming.value - current.value)
            <= value_margin
            && incoming.morphology_score
            > current.morphology_score
        ) {
            return true;
        }
    } else {
        if (incoming.value < current.value - value_margin) {
            return true;
        }

        if (
            fabsf(incoming.value - current.value)
            <= value_margin
            && incoming.morphology_score
            > current.morphology_score
        ) {
            return true;
        }
    }

    return false;
}

void ZeezAdaptiveDetector::pushCandidate(
    const ZeezCandidateFeatures &input
) {
    ZeezCandidateFeatures candidate = input;

    candidate.timing_score =
        timingScore(candidate.t_us);

    candidate.combined_score =
        clamp01(
            0.68f * candidate.morphology_score
            + 0.32f * candidate.timing_score
        );

    // -----------------------------------------------------------------------
    // v0.3.4 Peak Complex 合并
    // -----------------------------------------------------------------------
    // 平顶峰 / 宽峰上的 ADC 微抖动会产生多个同极性局部极值。
    // 它们属于同一个生理波峰，不应该各自进入周期 Winner 竞争。
    const float cluster_window_ms =
        candidateClusterWindowMs();

    for (size_t i = 0; i < candidate_pool_count_; ++i) {
        ZeezCandidateFeatures &current =
            candidate_pool_[i];

        if (
            current.polarity
            != candidate.polarity
        ) {
            continue;
        }

        const float distance_ms =
            fabsf(
                static_cast<float>(
                    candidate.t_us
                    - current.t_us
                ) / 1000.0f
            );

        if (distance_ms > cluster_window_ms) {
            continue;
        }

        if (
            shouldReplaceClusterRepresentative(
                current,
                candidate
            )
        ) {
            current = candidate;
        }

        return;
    }

    if (candidate_pool_count_ < CANDIDATE_POOL_CAPACITY) {
        candidate_pool_[candidate_pool_count_++] =
            candidate;
        return;
    }

    // 池满时保留分数更高、时间更新的候选。
    size_t weakest = 0;

    for (size_t i = 1; i < candidate_pool_count_; ++i) {
        if (
            candidate_pool_[i].combined_score
            < candidate_pool_[weakest].combined_score
        ) {
            weakest = i;
        }
    }

    if (
        candidate.combined_score
        > candidate_pool_[weakest].combined_score
    ) {
        candidate_pool_[weakest] = candidate;
    }
}

void ZeezAdaptiveDetector::pruneCandidatePool(
    int64_t now_us
) {
    // 最多保留最近 2.2 秒的候选。
    // 40 bpm 的一个周期约 1.5 秒，2.2 秒足以覆盖 rescue。
    const int64_t minimum_t_us =
        now_us - 2200000LL;

    size_t write = 0;

    for (size_t i = 0; i < candidate_pool_count_; ++i) {
        if (
            candidate_pool_[i].t_us
            >= minimum_t_us
        ) {
            candidate_pool_[write++] =
                candidate_pool_[i];
        }
    }

    candidate_pool_count_ = write;
}

void ZeezAdaptiveDetector::maybeUpdateAutocorrelation() {
    // -----------------------------------------------------------------------
    // 固定预算增量扫描
    // -----------------------------------------------------------------------
    // 每次 update() 最多处理 AUTOCORR_LAGS_PER_UPDATE 个 lag。
    // 不再出现“每 16 点突然做 3~4 万次相关运算”的突发负载。
    if (!autocorr_scan_active_) {
        if (!startAutocorrelationScan()) {
            return;
        }
    }

    for (
        uint8_t work = 0;
        work < AUTOCORR_LAGS_PER_UPDATE;
        ++work
    ) {
        if (
            !autocorr_scan_active_
            || autocorr_scan_lag_
            > autocorr_scan_max_lag_
        ) {
            break;
        }

        const size_t lag =
            autocorr_scan_lag_;

        float correlation = 0.0f;

        const bool valid =
            computeAutocorrelationLag(
                lag,
                correlation
            );

        if (lag < AUTOCORR_CORR_CAPACITY) {
            autocorr_scan_values_[lag] =
                correlation;

            autocorr_scan_valid_[lag] =
                valid;
        }

        ++autocorr_scan_lag_;

        // 扫描完成后一次性做很轻量的“找峰”。
        // 这里最多遍历约 150 个 float，不会阻塞采样。
        if (
            autocorr_scan_lag_
            > autocorr_scan_max_lag_
        ) {
            float period_ms = 0.0f;
            float confidence = 0.0f;

            if (
                finalizeAutocorrelationScan(
                    period_ms,
                    confidence
                )
            ) {
                autocorr_rr_ms_ =
                    period_ms;

                autocorr_confidence_ =
                    confidence;
            }

            autocorr_scan_active_ =
                false;

            updateExpectedRR();
            break;
        }
    }
}

bool ZeezAdaptiveDetector::startAutocorrelationScan() {
    // 搜索范围约 40~220 bpm。
    size_t min_lag =
        static_cast<size_t>(
            sample_rate_hz_
            * 60.0f
            / 220.0f
        );

    size_t max_lag =
        static_cast<size_t>(
            sample_rate_hz_
            * 60.0f
            / 40.0f
        );

    if (min_lag < 2) {
        min_lag = 2;
    }

    if (
        max_lag
        >= AUTOCORR_CORR_CAPACITY
    ) {
        max_lag =
            AUTOCORR_CORR_CAPACITY - 1;
    }

    // 第一轮至少需要“最长 lag + 32 对重叠数据”。
    // 125 Hz 下约 2 秒即可开始，不会用几十个点硬猜周期。
    const size_t minimum_points =
        max_lag + 32;

    if (
        signal_ring_.count
        < minimum_points
    ) {
        return false;
    }

    for (
        size_t lag = min_lag;
        lag <= max_lag;
        ++lag
    ) {
        autocorr_scan_values_[lag] =
            0.0f;

        autocorr_scan_valid_[lag] =
            false;
    }

    autocorr_scan_min_lag_ =
        min_lag;

    autocorr_scan_max_lag_ =
        max_lag;

    autocorr_scan_lag_ =
        min_lag;

    autocorr_scan_active_ =
        true;

    return true;
}

bool ZeezAdaptiveDetector::computeAutocorrelationLag(
    size_t lag,
    float &correlation
) const {
    if (
        lag == 0
        || lag >= signal_ring_.count
    ) {
        return false;
    }

    const size_t available_pairs =
        signal_ring_.count - lag;

    const size_t pair_count =
        available_pairs
        > AUTOCORR_MAX_PAIRS_PER_LAG
        ? AUTOCORR_MAX_PAIRS_PER_LAG
        : available_pairs;

    if (pair_count < 32) {
        return false;
    }

    // filtered PPG 已经去基线。
    // 继续减去环形缓冲区动态均值，可以降低慢漂移对相关系数的影响。
    const float mean =
        signal_stats_.mean();

    float numerator = 0.0f;
    float energy_a = 0.0f;
    float energy_b = 0.0f;

    for (
        size_t offset = 0;
        offset < pair_count;
        ++offset
    ) {
        SignalPoint a;
        SignalPoint b;

        if (
            !signal_ring_.getNewest(
                offset,
                a
            )
            || !signal_ring_.getNewest(
                offset + lag,
                b
            )
        ) {
            return false;
        }

        const float da =
            a.value - mean;

        const float db =
            b.value - mean;

        numerator +=
            da * db;

        energy_a +=
            da * da;

        energy_b +=
            db * db;
    }

    const float denominator =
        sqrtf(
            energy_a
            * energy_b
        );

    if (denominator <= 1e-6f) {
        return false;
    }

    correlation =
        numerator / denominator;

    return isfinite(
        correlation
    );
}

bool ZeezAdaptiveDetector::finalizeAutocorrelationScan(
    float &period_ms,
    float &confidence
) const {
    float global_best_corr =
        -1.0f;

    size_t global_best_lag =
        0;

    for (
        size_t lag = autocorr_scan_min_lag_;
        lag <= autocorr_scan_max_lag_;
        ++lag
    ) {
        if (
            lag >= AUTOCORR_CORR_CAPACITY
            || !autocorr_scan_valid_[lag]
        ) {
            continue;
        }

        const float corr =
            autocorr_scan_values_[lag];

        if (corr > global_best_corr) {
            global_best_corr = corr;
            global_best_lag = lag;
        }
    }

    if (
        global_best_lag == 0
        || global_best_corr < 0.12f
    ) {
        return false;
    }

    // 与 v0.3.1 保持相同的谐波策略：
    // 在接近全局最强的局部相关峰中选择最早一个，
    // 避免 2× / 3× 周期抢走基本周期。
    const float strong_threshold =
        global_best_corr * 0.90f;

    size_t selected_lag =
        global_best_lag;

    float selected_corr =
        global_best_corr;

    for (
        size_t lag =
            autocorr_scan_min_lag_ + 1;
        lag + 1
            <= autocorr_scan_max_lag_;
        ++lag
    ) {
        if (
            lag + 1
            >= AUTOCORR_CORR_CAPACITY
            || !autocorr_scan_valid_[lag - 1]
            || !autocorr_scan_valid_[lag]
            || !autocorr_scan_valid_[lag + 1]
        ) {
            continue;
        }

        const float current =
            autocorr_scan_values_[lag];

        const bool local_peak =
            current
                >= autocorr_scan_values_[lag - 1]
            && current
                >= autocorr_scan_values_[lag + 1];

        if (
            local_peak
            && current >= strong_threshold
            && current >= 0.18f
        ) {
            selected_lag =
                lag;

            selected_corr =
                current;

            break;
        }
    }

    period_ms =
        static_cast<float>(
            selected_lag
        )
        * sample_period_ms_;

    confidence =
        clamp01(
            (selected_corr - 0.10f)
            / 0.75f
        );

    return true;
}

void ZeezAdaptiveDetector::updateExpectedRR() {
    const float rr_median =
        rr_ring_.median();

    if (
        rr_ring_.count >= 2
        && rr_median > 0.0f
    ) {
        const float rr_mad =
            rr_ring_.mad();

        const float robust_variability =
            rr_median > 0.0f
            ? (
                1.4826f
                * rr_mad
                / rr_median
            )
            : 1.0f;

        // v0.3.1：
        // Accepted Beat 已被同极性锁约束后，稳定 RR 比单独的波形自相关
        // 更适合作为主节律锚点。
        if (robust_variability <= 0.20f) {
            expected_rr_ms_ =
                rr_median;

            if (
                autocorr_confidence_ >= 0.35f
                && autocorr_rr_ms_ > 0.0f
            ) {
                const float ratio =
                    autocorr_rr_ms_
                    / rr_median;

                if (
                    ratio >= 0.82f
                    && ratio <= 1.22f
                ) {
                    expected_rr_ms_ =
                        0.80f * rr_median
                        + 0.20f * autocorr_rr_ms_;
                }
            }

            return;
        }
    }

    if (
        autocorr_confidence_ >= 0.20f
        && autocorr_rr_ms_ > 0.0f
    ) {
        expected_rr_ms_ =
            autocorr_rr_ms_;
    } else if (rr_median > 0.0f) {
        expected_rr_ms_ =
            rr_median;
    }
}

void ZeezAdaptiveDetector::updatePhaseTrackerAfterAccept(
    int64_t accepted_t_us,
    bool first
) {
    if (expected_rr_ms_ <= 0.0f) {
        predicted_beat_t_us_ = 0;
        last_phase_error_ms_ = 0.0f;
        return;
    }

    const int64_t rr_us =
        static_cast<int64_t>(
            expected_rr_ms_ * 1000.0f
        );

    if (
        first
        || predicted_beat_t_us_ == 0
    ) {
        predicted_beat_t_us_ =
            accepted_t_us + rr_us;
        last_phase_error_ms_ = 0.0f;
        return;
    }

    const int64_t target_t_us =
        predicted_beat_t_us_;

    const float phase_error_ms =
        static_cast<float>(
            accepted_t_us - target_t_us
        ) / 1000.0f;

    last_phase_error_ms_ =
        phase_error_ms;

    // 只有当前 Winner 确实属于当前目标周期时才做小相位校正。
    // 大于 0.45×RR 通常表示漏掉了一整搏，不允许把 PLL 拉到错误相位。
    int64_t correction_us = 0;

    if (
        fabsf(phase_error_ms)
        <= expected_rr_ms_ * 0.45f
    ) {
        float bounded_error_ms =
            phase_error_ms;

        if (bounded_error_ms > 40.0f) {
            bounded_error_ms = 40.0f;
        }

        if (bounded_error_ms < -40.0f) {
            bounded_error_ms = -40.0f;
        }

        // 0.22 的小增益只修慢漂移，不跟随单搏 fiducial 抖动。
        correction_us =
            static_cast<int64_t>(
                bounded_error_ms
                * 0.22f
                * 1000.0f
            );
    }

    // 目标相位沿独立节律前进。
    // 若 accepted 已经落到下一周期，则跨过缺失目标，不用 Accepted 时间重新起算。
    int64_t next_target =
        target_t_us + rr_us;

    const int64_t acceptance_guard =
        static_cast<int64_t>(
            expected_rr_ms_
            * 0.35f
            * 1000.0f
        );

    uint8_t skipped_cycles = 0;

    while (
        next_target
        <= accepted_t_us + acceptance_guard
        && skipped_cycles < 3
    ) {
        next_target += rr_us;
        ++skipped_cycles;
    }

    predicted_beat_t_us_ =
        next_target + correction_us;
}

bool ZeezAdaptiveDetector::selectBestCandidate(
    float min_phase,
    float max_phase,
    float min_score,
    ZeezCandidateFeatures &selected
) const {
    if (
        (
            predicted_beat_t_us_ == 0
            && last_accepted_t_us_ == 0
        )
        || expected_rr_ms_ <= 0.0f
    ) {
        return false;
    }

    bool found = false;
    float best_score = -1.0f;

    for (size_t i = 0; i < candidate_pool_count_; ++i) {
        const ZeezCandidateFeatures &candidate =
            candidate_pool_[i];

        if (
            locked_polarity_ != 0
            && candidate.polarity
            != locked_polarity_
        ) {
            continue;
        }

        const float phase =
            phaseForTime(
                candidate.t_us
            );

        if (
            phase < min_phase
            || phase > max_phase
        ) {
            continue;
        }

        const float timing =
            timingScore(candidate.t_us);

        // 临近周期中心时，时间上下文权重稍微增加。
        const float combined =
            clamp01(
                0.64f * candidate.morphology_score
                + 0.36f * timing
            );

        if (
            combined >= min_score
            && combined > best_score
        ) {
            selected = candidate;
            selected.timing_score = timing;
            selected.combined_score = combined;
            best_score = combined;
            found = true;
        }
    }

    return found;
}

bool ZeezAdaptiveDetector::waveformRescue(
    int64_t now_us,
    ZeezCandidateFeatures &selected
) const {
    if (
        predicted_beat_t_us_ == 0
        || expected_rr_ms_ <= 0.0f
        || signal_ring_.count < 32
    ) {
        return false;
    }

    const int64_t search_start_us =
        predicted_beat_t_us_
        - static_cast<int64_t>(
            expected_rr_ms_ * 0.32f * 1000.0f
        );

    const int64_t search_end_us =
        predicted_beat_t_us_
        + static_cast<int64_t>(
            expected_rr_ms_ * 1.20f * 1000.0f
        );

    const int64_t actual_end_us =
        now_us < search_end_us
        ? now_us
        : search_end_us;

    const float mean =
        signal_stats_.mean();
    const float std =
        signal_stats_.stddev(1.0f);

    bool found = false;
    float best_z = 0.0f;
    SignalPoint best_point;

    for (size_t offset = 0; offset < signal_ring_.count; ++offset) {
        SignalPoint point;

        if (!signal_ring_.getNewest(
            offset,
            point
        )) {
            break;
        }

        if (point.t_us > actual_end_us) {
            continue;
        }

        if (point.t_us < search_start_us) {
            break;
        }

        float z = 0.0f;

        if (locked_polarity_ > 0) {
            z =
                (point.value - mean)
                / std;
        } else if (locked_polarity_ < 0) {
            z =
                (mean - point.value)
                / std;
        } else {
            z =
                fabsf(
                    point.value - mean
                ) / std;
        }

        if (z > best_z) {
            best_z = z;
            best_point = point;
            found = true;
        }
    }

    // Rescue 同样服从极性锁。
    // 低于局部 0.45σ 时更像平坦噪声，不强造心搏。
    if (!found || best_z < 0.45f) {
        return false;
    }

    selected = ZeezCandidateFeatures{};
    selected.seq = best_point.seq;
    selected.t_us = best_point.t_us;
    selected.value = best_point.value;
    selected.amplitude_z = best_z;
    selected.prominence_z = best_z;
    selected.slope_z = 0.0f;
    selected.curvature_z = 0.0f;
    selected.morphology_score =
        clamp01(0.30f + 0.18f * best_z);
    selected.timing_score =
        timingScore(selected.t_us);
    selected.combined_score =
        clamp01(
            0.45f * selected.morphology_score
            + 0.55f * selected.timing_score
        );

    selected.polarity =
        locked_polarity_ != 0
        ? locked_polarity_
        : (
            best_point.value >= mean
            ? 1
            : -1
        );

    return true;
}

bool ZeezAdaptiveDetector::bootstrapCandidate(
    ZeezCandidateFeatures &selected
) const {
    if (
        expected_rr_ms_ <= 0.0f
        || autocorr_confidence_ < 0.20f
        || candidate_pool_count_ == 0
    ) {
        return false;
    }

    // 从最近约 1.15 个预测周期里挑形态最强的极值作为相位锚点。
    SignalPoint newest;

    if (!signal_ring_.getNewest(0, newest)) {
        return false;
    }

    const int64_t minimum_t_us =
        newest.t_us
        - static_cast<int64_t>(
            expected_rr_ms_
            * 1.15f
            * 1000.0f
        );

    bool found = false;
    float best_score = 0.0f;

    for (size_t i = 0; i < candidate_pool_count_; ++i) {
        const ZeezCandidateFeatures &candidate =
            candidate_pool_[i];

        if (candidate.t_us < minimum_t_us) {
            continue;
        }

        if (
            candidate.morphology_score > best_score
        ) {
            selected = candidate;
            best_score = candidate.morphology_score;
            found = true;
        }
    }

    return found && best_score >= 0.34f;
}

ZeezDetectorEvent ZeezAdaptiveDetector::acceptCandidate(
    const ZeezCandidateFeatures &selected,
    bool rescued,
    float signal_score
) {
    ZeezDetectorEvent output;

    const bool first = (
        last_accepted_t_us_ == 0
    );

    if (locked_polarity_ == 0) {
        locked_polarity_ =
            selected.polarity;
    }

    if (
        selected.polarity
        != locked_polarity_
    ) {
        output.signal_score =
            signal_score;
        output.expected_rr_ms =
            expected_rr_ms_;
        output.locked_polarity =
            locked_polarity_;
        return output;
    }

    output.candidate = false;
    output.accepted = true;
    output.rescued = rescued;

    output.accepted_seq = selected.seq;
    output.accepted_t_us = selected.t_us;
    output.accepted_score = selected.combined_score;
    output.signal_score = signal_score;
    output.accepted_polarity =
        selected.polarity;
    output.locked_polarity =
        locked_polarity_;

    output.expected_rr_ms =
        expected_rr_ms_;

    if (first) {
        output.first = true;
        output.rr_ms = 0;
    } else {
        const int64_t rr_us =
            selected.t_us
            - last_accepted_t_us_;

        if (rr_us > 0) {
            int64_t rr_ms =
                rr_us / 1000LL;

            if (rr_ms > 65535) {
                rr_ms = 65535;
            }

            output.rr_ms =
                static_cast<uint16_t>(rr_ms);

            // 220~2000 ms 只用于保护节律预测历史。
            // 桌面端仍保留完整 RR 做更严格的 NN 清洗。
            if (
                output.rr_ms >= 220
                && output.rr_ms <= 2000
            ) {
                rr_ring_.push(
                    output.rr_ms
                );
            }
        }
    }

    last_accepted_t_us_ =
        selected.t_us;
    last_accepted_seq_ =
        selected.seq;

    ++accepted_count_total_;

    if (rescued) {
        ++rescue_count_total_;
    }

    updateExpectedRR();
    updatePhaseTrackerAfterAccept(
        selected.t_us,
        first
    );

    const float median_rr =
        rr_ring_.median();

    if (median_rr > 0.0f) {
        current_hr_bpm_ =
            60000.0f / median_rr;
    }

    output.hr_bpm =
        current_hr_bpm_;
    output.expected_rr_ms =
        expected_rr_ms_;
    output.predicted_beat_t_us =
        predicted_beat_t_us_;
    output.phase_error_ms =
        last_phase_error_ms_;

    // 一个周期只允许一个 winner。
    // 下一周期重新积累候选。
    candidate_pool_count_ = 0;

    return output;
}

ZeezDetectorEvent ZeezAdaptiveDetector::update(
    uint32_t seq,
    int64_t t_us,
    float filtered,
    bool wear
) {
    ZeezDetectorEvent output;

    if (!wear) {
        // 佩戴断开后，节律相位不能跨区间继承。
        reset();
        return output;
    }

    const float slope =
        has_previous_
        ? filtered - previous_value_
        : 0.0f;

    const float signal_score =
        currentSignalScore(
            filtered,
            slope
        );

    signal_stats_.push(filtered);
    slope_stats_.push(slope);

    SignalPoint current;
    current.seq = seq;
    current.t_us = t_us;
    current.value = filtered;
    current.slope = slope;

    signal_ring_.push(current);

    maybeUpdateAutocorrelation();
    pruneCandidatePool(t_us);

    ZeezCandidateFeatures candidate;

    if (
        has_previous_
        && detectLocalExtremum(candidate)
    ) {
        ++candidate_count_total_;

        pushCandidate(candidate);

        output.candidate = true;
        output.candidate_seq =
            candidate.seq;
        output.candidate_t_us =
            candidate.t_us;
    }

    output.signal_score = signal_score;
    output.expected_rr_ms =
        expected_rr_ms_;
    output.locked_polarity =
        locked_polarity_;
    output.predicted_beat_t_us =
        predicted_beat_t_us_;
    output.phase_error_ms =
        last_phase_error_ms_;

    // ------------------------------------------------------------------------
    // 没有相位锚点：先用自相关确定基本周期，再选择一个形态最强的真实极值。
    // ------------------------------------------------------------------------
    if (
        last_accepted_t_us_ == 0
        && expected_rr_ms_ > 0.0f
    ) {
        ZeezCandidateFeatures bootstrap;

        if (bootstrapCandidate(bootstrap)) {
            ZeezDetectorEvent accepted =
                acceptCandidate(
                    bootstrap,
                    false,
                    signal_score
                );

            accepted.candidate =
                output.candidate;
            accepted.candidate_seq =
                output.candidate_seq;
            accepted.candidate_t_us =
                output.candidate_t_us;

            has_previous_ = true;
            previous_value_ = filtered;
            previous_slope_ = slope;
            previous_seq_ = seq;
            previous_t_us_ = t_us;

            return accepted;
        }
    }

    // ------------------------------------------------------------------------
    // 已建立相位：一个预测周期内允许多个候选竞争。
    // ------------------------------------------------------------------------
    if (
        predicted_beat_t_us_ != 0
        && expected_rr_ms_ > 0.0f
    ) {
        const float phase =
            phaseForTime(
                t_us
            );

        ZeezCandidateFeatures selected;

        // 第一决策点：约到达预测周期后 1.06 倍。
        // 主峰稍早/稍晚都已经进入候选池。
        if (
            phase >= 1.06f
            && selectBestCandidate(
                0.72f,
                1.55f,
                0.40f * score_threshold_scale_,
                selected
            )
        ) {
            ZeezDetectorEvent accepted =
                acceptCandidate(
                    selected,
                    false,
                    signal_score
                );

            accepted.candidate =
                output.candidate;
            accepted.candidate_seq =
                output.candidate_seq;
            accepted.candidate_t_us =
                output.candidate_t_us;

            has_previous_ = true;
            previous_value_ = filtered;
            previous_slope_ = slope;
            previous_seq_ = seq;
            previous_t_us_ = t_us;

            return accepted;
        }

        // Rescue 1：预测周期已经明显超时，降低候选分数要求。
        if (
            phase >= 1.35f
            && selectBestCandidate(
                0.72f,
                2.20f,
                0.24f * score_threshold_scale_,
                selected
            )
        ) {
            ZeezDetectorEvent accepted =
                acceptCandidate(
                    selected,
                    true,
                    signal_score
                );

            accepted.candidate =
                output.candidate;
            accepted.candidate_seq =
                output.candidate_seq;
            accepted.candidate_t_us =
                output.candidate_t_us;

            has_previous_ = true;
            previous_value_ = filtered;
            previous_slope_ = slope;
            previous_seq_ = seq;
            previous_t_us_ = t_us;

            return accepted;
        }

        // Rescue 2：候选池也没有合适结果，直接在该周期波形中寻找最显著极值。
        if (phase >= 1.70f) {
            ZeezCandidateFeatures rescue;

            if (
                waveformRescue(
                    t_us,
                    rescue
                )
            ) {
                ZeezDetectorEvent accepted =
                    acceptCandidate(
                        rescue,
                        true,
                        signal_score
                    );

                accepted.candidate =
                    output.candidate;
                accepted.candidate_seq =
                    output.candidate_seq;
                accepted.candidate_t_us =
                    output.candidate_t_us;

                has_previous_ = true;
                previous_value_ = filtered;
                previous_slope_ = slope;
                previous_seq_ = seq;
                previous_t_us_ = t_us;

                return accepted;
            }
        }
    }

    has_previous_ = true;
    previous_value_ = filtered;
    previous_slope_ = slope;
    previous_seq_ = seq;
    previous_t_us_ = t_us;

    return output;
}
