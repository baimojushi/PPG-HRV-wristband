#include "acquisition.h"

#include <esp_timer.h>
#include <freertos/task.h>

#include "config.h"
#include "data_types.h"
#include "legacy_hrv.h"
#include "zeezPPG.h"

namespace {

// v0.3.2：完整算法源码位于 firmware/lib/zeezPPG。
// 采集任务独占算法对象，其他任务只消费 POD 队列。
zeezPPG ppg(
    PPG_INPUT_PIN,
    PPG_SAMPLE_RATE_HZ
);

QueueHandle_t g_sample_queue = nullptr;
QueueHandle_t g_beat_queue = nullptr;
QueueHandle_t g_metric_queue = nullptr;
Diagnostics *g_diagnostics = nullptr;

LegacyHrvAccumulator g_legacy_hrv;

uint32_t g_sample_seq = 0;
int64_t g_last_metric_us = 0;

uint16_t buildSampleFlags(
    int16_t raw,
    bool wear
) {
    uint16_t flags = SAMPLE_FLAG_NONE;

    if (wear) {
        flags |= SAMPLE_FLAG_WEAR;
    }
    if (raw <= QUALITY_ADC_LOW) {
        flags |= SAMPLE_FLAG_CLIP_LOW;
    }
    if (raw >= QUALITY_ADC_HIGH) {
        flags |= SAMPLE_FLAG_CLIP_HIGH;
    }

    const UBaseType_t depth =
        uxQueueMessagesWaiting(
            g_sample_queue
        );

    if (
        depth
        >= (
            SAMPLE_QUEUE_LENGTH
            * 3
            / 4
        )
    ) {
        flags |= SAMPLE_FLAG_QUEUE_PRESSURE;
    }

    return flags;
}

void enqueueSample(
    const SampleFrame &frame
) {
    if (
        xQueueSend(
            g_sample_queue,
            &frame,
            0
        ) != pdTRUE
    ) {
        g_diagnostics->onSampleDrop();
        return;
    }

    const uint16_t depth =
        static_cast<uint16_t>(
            uxQueueMessagesWaiting(
                g_sample_queue
            )
        );

    g_diagnostics->observeSampleQueueDepth(
        depth
    );
}

void enqueueBeat(
    const BeatFrame &frame
) {
    if (
        xQueueSend(
            g_beat_queue,
            &frame,
            0
        ) != pdTRUE
    ) {
        g_diagnostics->onBeatDrop();
    }
}

void enqueueMetric(
    const MetricFrame &frame
) {
    if (
        xQueueSend(
            g_metric_queue,
            &frame,
            0
        ) != pdTRUE
    ) {
        g_diagnostics->onMetricDrop();
    }
}

void acquisitionTask(void *param) {
    analogReadResolution(
        PPG_ADC_RESOLUTION_BITS
    );

    ppg.setWearThreshold(
        PPG_WEAR_THRESHOLD
    );

    // 11.0 继续作为历史兼容入口。
    // 新算法只把它映射为小范围综合分数门灵敏度。
    ppg.setPeakThresholdFactor(
        PPG_PEAK_THRESHOLD_FACTOR
    );

    g_last_metric_us =
        esp_timer_get_time();

    while (true) {
        if (!ppg.checkSampleInterval()) {
            taskYIELD();
            continue;
        }

        const uint32_t seq =
            g_sample_seq++;

        const int64_t now_us =
            esp_timer_get_time();

        // 所有动态统计、环形缓冲、候选竞争和周期 rescue
        // 都在项目内 zeezPPG 中完成。
        ppg.ppgProcess(
            seq,
            now_us
        );

        const bool wear =
            ppg.getPpgisWear();

        SampleFrame sample;
        sample.seq = seq;
        sample.t_us = now_us;

        sample.raw =
            static_cast<int16_t>(
                ppg.getRawPPG()
            );

        sample.avg =
            static_cast<int16_t>(
                ppg.getAvgPPG()
            );

        sample.filtered =
            static_cast<int16_t>(
                ppg.getFilterPPG()
            );

        // 这里是“局部极值 Candidate 脉冲”。
        // 最终心搏只从 BeatFrame 输出。
        sample.peak =
            ppg.getPpgCandidate()
            ? 1
            : 0;

        sample.detector_score =
            ppg.getPpgScore();

        sample.expected_rr_ms =
            ppg.getExpectedRR();

        sample.hr_bpm =
            ppg.getPpgHr();

        sample.flags =
            buildSampleFlags(
                sample.raw,
                wear
            );

        enqueueSample(sample);

        // -------------------------------------------------------------------
        // 一个预测周期内多个 Candidate 竞争后，只弹出一个 Accepted Beat。
        // -------------------------------------------------------------------
        zeezPPGBeat accepted;

        if (
            ppg.popAcceptedBeat(
                accepted
            )
        ) {
            BeatFrame beat;

            beat.seq =
                accepted.seq;
            beat.t_us =
                accepted.t_us;
            beat.rr_ms =
                accepted.rr_ms;
            beat.hr_bpm =
                accepted.hr_bpm;
            beat.score =
                accepted.score;

            beat.flags |=
                BEAT_FLAG_WEAR;
            beat.flags |=
                BEAT_FLAG_ADAPTIVE_ACCEPTED;

            if (accepted.first) {
                beat.flags |=
                    BEAT_FLAG_FIRST;
            }

            if (accepted.rescued) {
                beat.flags |=
                    BEAT_FLAG_RESCUED;
            }

            if (
                beat.rr_ms > 0
                && (
                    beat.rr_ms
                    < RR_HARD_MIN_MS
                    || beat.rr_ms
                    > RR_HARD_MAX_MS
                )
            ) {
                beat.flags |=
                    BEAT_FLAG_RR_HARD_INVALID;
            }

            if (beat.rr_ms > 0) {
                g_legacy_hrv.pushRR(
                    beat.rr_ms,
                    true
                );
            }

            enqueueBeat(beat);
        }

        if (
            (now_us - g_last_metric_us)
            >= static_cast<int64_t>(
                HRV_UPDATE_PERIOD_MS
            ) * 1000LL
        ) {
            enqueueMetric(
                g_legacy_hrv.compute(
                    now_us
                )
            );

            g_last_metric_us =
                now_us;
        }
    }
}

} // namespace

void startAcquisitionTask(
    QueueHandle_t sample_queue,
    QueueHandle_t beat_queue,
    QueueHandle_t metric_queue,
    Diagnostics *diagnostics
) {
    g_sample_queue =
        sample_queue;
    g_beat_queue =
        beat_queue;
    g_metric_queue =
        metric_queue;
    g_diagnostics =
        diagnostics;

    xTaskCreatePinnedToCore(
        acquisitionTask,
        "PPG Acquisition",
        ACQUISITION_TASK_STACK,
        nullptr,
        ACQUISITION_TASK_PRIORITY,
        nullptr,
        ACQUISITION_CORE
    );
}
