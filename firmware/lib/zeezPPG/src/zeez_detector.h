#pragma once

#include <stddef.h>
#include <stdint.h>

// ============================================================================
// ZeezAdaptiveDetector
// ============================================================================
//
// 这一层完全不依赖 Arduino API，可以直接在 PC 上用 g++ 回归测试。
//
// 设计目标：
// 1. 不把单个阈值越过直接等同于心搏；
// 2. 用环形缓冲区持续维护最近信号、斜率、RR 和候选；
// 3. 同时利用“形态”和“周期”两个上下文；
// 4. 允许宽峰、缓慢下降、幅值变化，不再依赖固定 450 ms 超时确认；
// 5. 发生漏检风险时，从预测周期窗口里做 rescue search；
// 6. 算法输出时间戳始终落在真实局部极值，而不是后续确认时刻。
//

struct ZeezDetectorEvent {
    bool candidate = false;
    bool accepted = false;
    bool rescued = false;
    bool first = false;

    uint32_t candidate_seq = 0;
    int64_t candidate_t_us = 0;

    uint32_t accepted_seq = 0;
    int64_t accepted_t_us = 0;

    uint16_t rr_ms = 0;
    float hr_bpm = 0.0f;

    // 当前采样的动态形态分数，0~1。
    // 它是算法评分，不是医学概率。
    float signal_score = 0.0f;

    // 被选中候选的最终综合分数，0~1。
    float accepted_score = 0.0f;

    // 当前周期预测值，0 表示尚未建立稳定周期。
    float expected_rr_ms = 0.0f;
};

struct ZeezCandidateFeatures {
    uint32_t seq = 0;
    int64_t t_us = 0;

    float value = 0.0f;
    float morphology_score = 0.0f;
    float timing_score = 0.0f;
    float combined_score = 0.0f;

    float amplitude_z = 0.0f;
    float prominence_z = 0.0f;
    float slope_z = 0.0f;
    float curvature_z = 0.0f;

    int8_t polarity = 0;  // +1 局部最大值，-1 局部最小值
};

class ZeezAdaptiveDetector {
public:
    explicit ZeezAdaptiveDetector(uint16_t sample_rate_hz = 125);

    void reset();

    // 兼容早期 setPeakThresholdFactor()。
    // 11.0 是中性值；这里只对候选/决策分数门做小范围缩放，
    // 不再作为“幅值超过 N×标准差就直接算心搏”的单一裁判。
    void setLegacyPeakFactor(float factor);

    ZeezDetectorEvent update(
        uint32_t seq,
        int64_t t_us,
        float filtered,
        bool wear
    );

    float expectedRRMs() const {
        return expected_rr_ms_;
    }

    float autocorrConfidence() const {
        return autocorr_confidence_;
    }

    float currentHrBpm() const {
        return current_hr_bpm_;
    }

    uint32_t candidateCount() const {
        return candidate_count_total_;
    }

    uint32_t acceptedCount() const {
        return accepted_count_total_;
    }

    uint32_t rescueCount() const {
        return rescue_count_total_;
    }

private:
    // ------------------------------------------------------------------------
    // 固定内存：经典 ESP32 也能轻松承受。
    // ------------------------------------------------------------------------
    static constexpr size_t SIGNAL_RING_CAPACITY = 320;   // 2.56 s @ 125 Hz
    static constexpr size_t RR_RING_CAPACITY = 9;
    static constexpr size_t CANDIDATE_POOL_CAPACITY = 16;

    struct SignalPoint {
        uint32_t seq = 0;
        int64_t t_us = 0;
        float value = 0.0f;
        float slope = 0.0f;
    };

    struct RunningRing {
        float values[SIGNAL_RING_CAPACITY] = {};
        size_t write_index = 0;
        size_t count = 0;

        double sum = 0.0;
        double sum_sq = 0.0;

        void clear();
        void push(float value);
        float mean() const;
        float stddev(float floor_value = 1e-3f) const;
        float minLast(size_t n) const;
        float maxLast(size_t n) const;
        float maxAbsLast(size_t n) const;
    };

    struct SignalRing {
        SignalPoint points[SIGNAL_RING_CAPACITY] = {};
        size_t write_index = 0;
        size_t count = 0;

        void clear();
        void push(const SignalPoint &point);
        bool getNewest(size_t offset, SignalPoint &out) const;
    };

    struct RrRing {
        uint16_t values[RR_RING_CAPACITY] = {};
        size_t write_index = 0;
        size_t count = 0;

        void clear();
        void push(uint16_t rr_ms);
        float median() const;
        float mad() const;
    };

    uint16_t sample_rate_hz_;
    float sample_period_ms_;

    RunningRing signal_stats_;
    RunningRing slope_stats_;
    SignalRing signal_ring_;
    RrRing rr_ring_;

    ZeezCandidateFeatures candidate_pool_[CANDIDATE_POOL_CAPACITY] = {};
    size_t candidate_pool_count_ = 0;

    bool has_previous_ = false;
    float previous_value_ = 0.0f;
    float previous_slope_ = 0.0f;
    uint32_t previous_seq_ = 0;
    int64_t previous_t_us_ = 0;

    int64_t last_accepted_t_us_ = 0;
    uint32_t last_accepted_seq_ = 0;

    float expected_rr_ms_ = 0.0f;
    float autocorr_rr_ms_ = 0.0f;
    float autocorr_confidence_ = 0.0f;
    uint32_t samples_since_autocorr_ = 0;

    float current_hr_bpm_ = 0.0f;

    uint32_t candidate_count_total_ = 0;
    uint32_t accepted_count_total_ = 0;
    uint32_t rescue_count_total_ = 0;

    float legacy_peak_factor_ = 11.0f;
    float score_threshold_scale_ = 1.0f;

    // ------------------------------------------------------------------------
    // 动态特征
    // ------------------------------------------------------------------------
    float sigmoid(float x) const;
    float clamp01(float value) const;

    float currentSignalScore(
        float value,
        float slope
    ) const;

    bool detectLocalExtremum(
        ZeezCandidateFeatures &candidate
    ) const;

    float morphologyScore(
        ZeezCandidateFeatures &candidate
    ) const;

    float timingScore(int64_t candidate_t_us) const;

    void pushCandidate(
        const ZeezCandidateFeatures &candidate
    );

    void pruneCandidatePool(int64_t now_us);

    // ------------------------------------------------------------------------
    // 周期预测
    // ------------------------------------------------------------------------
    void maybeUpdateAutocorrelation();
    bool estimateAutocorrelationPeriod(
        float &period_ms,
        float &confidence
    ) const;

    void updateExpectedRR();

    // ------------------------------------------------------------------------
    // 周期内“一个 winner”
    // ------------------------------------------------------------------------
    bool selectBestCandidate(
        float min_phase,
        float max_phase,
        float min_score,
        ZeezCandidateFeatures &selected
    ) const;

    bool waveformRescue(
        int64_t now_us,
        ZeezCandidateFeatures &selected
    ) const;

    ZeezDetectorEvent acceptCandidate(
        const ZeezCandidateFeatures &selected,
        bool rescued,
        float signal_score
    );

    // 初始阶段还没有 RR 时，用自相关周期 + 最近候选建立相位锚点。
    bool bootstrapCandidate(
        ZeezCandidateFeatures &selected
    ) const;
};
