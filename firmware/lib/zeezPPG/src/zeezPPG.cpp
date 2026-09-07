#include "zeezPPG.h"

#include <math.h>

namespace {

float alphaFromTau(
    float dt_seconds,
    float tau_seconds
) {
    if (tau_seconds <= 0.0f) {
        return 1.0f;
    }

    return dt_seconds / (
        tau_seconds + dt_seconds
    );
}

} // namespace

zeezPPG::zeezPPG(
    uint8_t inputPin,
    uint16_t sampleRateHz
)
    : input_pin_(inputPin),
      sample_rate_hz_(sampleRateHz),
      sample_period_us_(
          static_cast<uint32_t>(
              1000000UL / sampleRateHz
          )
      ),
      detector_(sampleRateHz) {
    const float dt =
        1.0f / static_cast<float>(
            sample_rate_hz_
        );

    // 三个时间尺度：
    // - average：抑制 ADC 单点毛刺；
    // - baseline：跟随几秒级 DC 漂移；
    // - pulse：对去基线脉搏再做轻平滑。
    //
    // 系数由采样率和时间常数推导，不依赖“某个 ADC 幅值刚好是多少”。
    average_alpha_ =
        alphaFromTau(dt, 0.025f);

    baseline_alpha_ =
        alphaFromTau(dt, 1.20f);

    pulse_alpha_ =
        alphaFromTau(dt, 0.020f);
}

void zeezPPG::setWearThreshold(
    int threshold
) {
    wear_threshold_ = threshold;
}

void zeezPPG::setPeakThresholdFactor(
    float factor
) {
    detector_.setLegacyPeakFactor(
        factor
    );
}

bool zeezPPG::checkSampleInterval() {
    const uint32_t now_us = micros();

    if (last_sample_us_ == 0) {
        last_sample_us_ = now_us;
        return true;
    }

    const uint32_t elapsed =
        now_us - last_sample_us_;

    if (elapsed < sample_period_us_) {
        return false;
    }

    // 尽量保持理论节拍。
    // 如果调度延迟已经跨过多个周期，直接重新锚定 now，避免疯狂补采样。
    if (elapsed > sample_period_us_ * 3UL) {
        last_sample_us_ = now_us;
    } else {
        last_sample_us_ += sample_period_us_;
    }

    return true;
}

void zeezPPG::updateWearState() {
    const bool high =
        avg_ppg_ > wear_threshold_;

    // 约 0.25 秒去抖。
    const uint16_t stable_samples =
        static_cast<uint16_t>(
            sample_rate_hz_ / 4
        );

    if (high) {
        wear_low_count_ = 0;

        if (
            wear_high_count_
            < stable_samples
        ) {
            ++wear_high_count_;
        }

        if (
            wear_high_count_
            >= stable_samples
        ) {
            is_wear_ = true;
        }
    } else {
        wear_high_count_ = 0;

        if (
            wear_low_count_
            < stable_samples
        ) {
            ++wear_low_count_;
        }

        if (
            wear_low_count_
            >= stable_samples
        ) {
            is_wear_ = false;
        }
    }
}

void zeezPPG::updateFilter(int raw) {
    if (!filter_initialized_) {
        average_ema_ =
            static_cast<float>(raw);

        baseline_ema_ =
            static_cast<float>(raw);

        pulse_ema_ = 0.0f;

        filter_initialized_ = true;
    }

    average_ema_ +=
        average_alpha_
        * (
            static_cast<float>(raw)
            - average_ema_
        );

    baseline_ema_ +=
        baseline_alpha_
        * (
            average_ema_
            - baseline_ema_
        );

    const float pulse =
        average_ema_
        - baseline_ema_;

    pulse_ema_ +=
        pulse_alpha_
        * (
            pulse
            - pulse_ema_
        );

    avg_ppg_ =
        static_cast<int>(
            lroundf(average_ema_)
        );

    // 新 filtered 是去基线后的有符号 PPG。
    // Candidate 层同时识别正峰和负峰；第一个稳定 Winner 后，Accepted 层锁定同一极性。
    filtered_ppg_ =
        static_cast<int>(
            lroundf(pulse_ema_)
        );
}

void zeezPPG::ppgProcess(
    uint32_t seq,
    int64_t t_us
) {
    raw_ppg_ = analogRead(
        input_pin_
    );

    updateFilter(raw_ppg_);
    updateWearState();

    last_event_ =
        detector_.update(
            seq,
            t_us,
            static_cast<float>(
                filtered_ppg_
            ),
            is_wear_
        );

    if (last_event_.accepted) {
        accepted_pending_ = true;

        pending_beat_ = zeezPPGBeat{};
        pending_beat_.valid = true;
        pending_beat_.rescued =
            last_event_.rescued;
        pending_beat_.first =
            last_event_.first;

        pending_beat_.seq =
            last_event_.accepted_seq;
        pending_beat_.t_us =
            last_event_.accepted_t_us;

        pending_beat_.rr_ms =
            last_event_.rr_ms;
        pending_beat_.hr_bpm =
            last_event_.hr_bpm;
        pending_beat_.score =
            last_event_.accepted_score;
    }
}

void zeezPPG::ppgProcess() {
    const uint32_t now_us =
        micros();

    ppgProcess(
        compatibility_seq_++,
        static_cast<int64_t>(now_us)
    );
}

bool zeezPPG::popAcceptedBeat(
    zeezPPGBeat &beat
) {
    if (!accepted_pending_) {
        return false;
    }

    beat = pending_beat_;
    accepted_pending_ = false;

    return true;
}
