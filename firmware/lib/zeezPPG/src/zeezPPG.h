#pragma once

#include <Arduino.h>

#include "zeez_detector.h"

// ============================================================================
// zeezPPG
// ============================================================================
//
// 重新实现的项目内 PPG 算法库。
//
// 保留早期工程熟悉的调用方式：
//   zeezPPG ppg(pin, sampleRate);
//   ppg.setWearThreshold(...);
//   ppg.setPeakThresholdFactor(11.0f);
//   ppg.checkSampleInterval();
//   ppg.ppgProcess(...);
//
// 与旧版本最重要的语义变化：
// - getPpgCandidate()：形态算法发现的局部极值候选；
// - popAcceptedBeat()：一个预测周期内竞争后的最终心搏；
// - getPpgPeak()：兼容接口，等价于“本采样处理后产生 Accepted Beat”；
// - getPpgHr()：只基于 Accepted RR 的鲁棒心率。
//

struct zeezPPGBeat {
    bool valid = false;
    bool rescued = false;
    bool first = false;

    uint32_t seq = 0;
    int64_t t_us = 0;

    uint16_t rr_ms = 0;
    float hr_bpm = 0.0f;
    float score = 0.0f;
};

class zeezPPG {
public:
    zeezPPG(
        uint8_t inputPin,
        uint16_t sampleRateHz
    );

    void setWearThreshold(int threshold);
    void setPeakThresholdFactor(float factor);

    bool checkSampleInterval();

    // 推荐新接口：由采集任务传入统一 seq / t_us。
    void ppgProcess(
        uint32_t seq,
        int64_t t_us
    );

    // 兼容旧调用；时间使用 micros()，不建议用于最终 RR。
    void ppgProcess();

    int getRawPPG() const {
        return raw_ppg_;
    }

    int getAvgPPG() const {
        return avg_ppg_;
    }

    int getFilterPPG() const {
        return filtered_ppg_;
    }

    bool getPpgCandidate() const {
        return last_event_.candidate;
    }

    float getPpgScore() const {
        return last_event_.signal_score;
    }

    float getExpectedRR() const {
        return detector_.expectedRRMs();
    }

    // 兼容接口：表示本轮 ppgProcess 是否最终确认了心搏。
    int getPpgPeak() const {
        return last_event_.accepted ? 1 : 0;
    }

    float getPpgHr() const {
        return detector_.currentHrBpm();
    }

    // 最终 HRV 仍由独立 RR/NN 管线计算；保留接口避免旧代码编译失败。
    float getPpgHrv() const {
        return 0.0f;
    }

    bool getPpgisWear() const {
        return is_wear_;
    }

    bool popAcceptedBeat(
        zeezPPGBeat &beat
    );

    uint32_t getCandidateCount() const {
        return detector_.candidateCount();
    }

    uint32_t getAcceptedCount() const {
        return detector_.acceptedCount();
    }

    uint32_t getRescueCount() const {
        return detector_.rescueCount();
    }

    float getAutocorrConfidence() const {
        return detector_.autocorrConfidence();
    }

private:
    uint8_t input_pin_;
    uint16_t sample_rate_hz_;
    uint32_t sample_period_us_;

    uint32_t last_sample_us_ = 0;

    int wear_threshold_ = 1;
    bool is_wear_ = false;
    uint16_t wear_high_count_ = 0;
    uint16_t wear_low_count_ = 0;

    bool filter_initialized_ = false;

    float average_ema_ = 0.0f;
    float baseline_ema_ = 0.0f;
    float pulse_ema_ = 0.0f;

    float average_alpha_ = 0.0f;
    float baseline_alpha_ = 0.0f;
    float pulse_alpha_ = 0.0f;

    int raw_ppg_ = 0;
    int avg_ppg_ = 0;
    int filtered_ppg_ = 0;

    ZeezAdaptiveDetector detector_;
    ZeezDetectorEvent last_event_;

    bool accepted_pending_ = false;
    zeezPPGBeat pending_beat_;

    uint32_t compatibility_seq_ = 0;

    void updateWearState();
    void updateFilter(int raw);
};
