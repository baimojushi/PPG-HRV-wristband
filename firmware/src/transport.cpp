#include "transport.h"

#include <esp_timer.h>
#include <freertos/task.h>

#include "config.h"
#include "data_types.h"

namespace {

BluetoothSerial BTSerial;

QueueHandle_t g_sample_queue = nullptr;
QueueHandle_t g_beat_queue = nullptr;
QueueHandle_t g_metric_queue = nullptr;
Diagnostics *g_diagnostics = nullptr;

int64_t g_last_diagnostic_us = 0;

// body 和最终 frame 分开，避免 snprintf 输入输出缓冲区重叠。
char g_body_buffer[224];
char g_frame_buffer[256];

// CRC-16/CCITT-FALSE：poly=0x1021, init=0xFFFF。
// Python 接收端使用完全相同的实现。
uint16_t crc16Ccitt(const char *data) {
    uint16_t crc = 0xFFFF;

    while (*data != '\0') {
        crc ^= static_cast<uint16_t>(
            static_cast<uint8_t>(*data)
        ) << 8;

        for (uint8_t bit = 0; bit < 8; ++bit) {
            if (crc & 0x8000) {
                crc = static_cast<uint16_t>(
                    (crc << 1) ^ 0x1021
                );
            } else {
                crc = static_cast<uint16_t>(
                    crc << 1
                );
            }
        }

        ++data;
    }

    return crc;
}

void writeLine(const char *line) {
    // USB 与经典蓝牙都在低优先级传输任务。
    // 传输阻塞最多导致队列压力，不允许阻塞 125 Hz 采集任务。
    Serial.println(line);

    if (BTSerial.hasClient()) {
        BTSerial.println(line);
    }
}

void writeFramedBody(const char *body) {
    // v4 格式：
    // @S,seq,t_us,...*ABCD\r\n
    //
    // @ 用于接收端快速重同步；
    // CRC 用于区分“字段恰好还能解析”与“内容已经损坏”。
    const uint16_t crc = crc16Ccitt(body);

    snprintf(
        g_frame_buffer,
        sizeof(g_frame_buffer),
        "@%s*%04X",
        body,
        static_cast<unsigned>(crc)
    );

    writeLine(g_frame_buffer);
}

void sendProtocolHello() {
    // v4 只扩展 Sample / Beat 字段，帧头和 CRC 机制保持不变。
    writeLine("#PPGHRV,4");
    writeLine("#FRAME=@BODY*CRC16_CCITT");
    writeLine("#S=sample+score+expectedRR,#B=acceptedBeat+score,#M=metric,#D=diagnostic");
}

void sendSample(const SampleFrame &s) {
    // v4 Sample:
    // S,seq,t_us,raw,avg,filtered,candidate,score,expected_rr,hr_bpm,flags
    snprintf(
        g_body_buffer,
        sizeof(g_body_buffer),
        "S,%lu,%lld,%d,%d,%d,%u,%.3f,%.1f,%.1f,%u",
        static_cast<unsigned long>(s.seq),
        static_cast<long long>(s.t_us),
        static_cast<int>(s.raw),
        static_cast<int>(s.avg),
        static_cast<int>(s.filtered),
        static_cast<unsigned>(s.peak),
        static_cast<double>(s.detector_score),
        static_cast<double>(s.expected_rr_ms),
        static_cast<double>(s.hr_bpm),
        static_cast<unsigned>(s.flags)
    );

    writeFramedBody(g_body_buffer);
}

void sendBeat(const BeatFrame &b) {
    // v4 Beat:
    // B,seq,t_us,rr_ms,hr_bpm,score,flags
    snprintf(
        g_body_buffer,
        sizeof(g_body_buffer),
        "B,%lu,%lld,%u,%.1f,%.3f,%u",
        static_cast<unsigned long>(b.seq),
        static_cast<long long>(b.t_us),
        static_cast<unsigned>(b.rr_ms),
        static_cast<double>(b.hr_bpm),
        static_cast<double>(b.score),
        static_cast<unsigned>(b.flags)
    );

    writeFramedBody(g_body_buffer);
}

void sendMetric(const MetricFrame &m) {
    snprintf(
        g_body_buffer,
        sizeof(g_body_buffer),
        "M,%lld,%.2f,%u,%.4f,%u",
        static_cast<long long>(m.t_us),
        static_cast<double>(m.rmssd_ms),
        static_cast<unsigned>(m.valid_rr_count),
        static_cast<double>(m.artifact_ratio),
        static_cast<unsigned>(m.valid)
    );

    writeFramedBody(g_body_buffer);
}

void sendDiagnostic(const DiagnosticFrame &d) {
    snprintf(
        g_body_buffer,
        sizeof(g_body_buffer),
        "D,%lld,%lu,%lu,%lu,%u,%u",
        static_cast<long long>(d.t_us),
        static_cast<unsigned long>(d.sample_drop_count),
        static_cast<unsigned long>(d.beat_drop_count),
        static_cast<unsigned long>(d.metric_drop_count),
        static_cast<unsigned>(d.sample_queue_depth),
        static_cast<unsigned>(d.sample_queue_high_water)
    );

    writeFramedBody(g_body_buffer);
}

void transportTask(void *param) {
    sendProtocolHello();
    g_last_diagnostic_us = esp_timer_get_time();

    while (true) {
        bool sent_anything = false;

        // 每轮最多发送 32 个 Sample，防止 Beat / Metric / Diagnostic 长期饥饿。
        for (uint8_t i = 0; i < 32; ++i) {
            SampleFrame sample;

            if (
                xQueueReceive(
                    g_sample_queue,
                    &sample,
                    0
                ) != pdTRUE
            ) {
                break;
            }

            sendSample(sample);
            sent_anything = true;
        }

        BeatFrame beat;
        while (
            xQueueReceive(
                g_beat_queue,
                &beat,
                0
            ) == pdTRUE
        ) {
            sendBeat(beat);
            sent_anything = true;
        }

        MetricFrame metric;
        while (
            xQueueReceive(
                g_metric_queue,
                &metric,
                0
            ) == pdTRUE
        ) {
            sendMetric(metric);
            sent_anything = true;
        }

        const int64_t now_us = esp_timer_get_time();

        if (
            (now_us - g_last_diagnostic_us)
            >= static_cast<int64_t>(
                DIAGNOSTIC_PERIOD_MS
            ) * 1000LL
        ) {
            const uint16_t depth =
                static_cast<uint16_t>(
                    uxQueueMessagesWaiting(
                        g_sample_queue
                    )
                );

            sendDiagnostic(
                g_diagnostics->snapshot(
                    now_us,
                    depth
                )
            );
            g_last_diagnostic_us = now_us;
            sent_anything = true;
        }

        if (!sent_anything) {
            vTaskDelay(
                pdMS_TO_TICKS(1)
            );
        } else {
            taskYIELD();
        }
    }
}

} // namespace

void startTransportTask(
    QueueHandle_t sample_queue,
    QueueHandle_t beat_queue,
    QueueHandle_t metric_queue,
    Diagnostics *diagnostics
) {
    g_sample_queue = sample_queue;
    g_beat_queue = beat_queue;
    g_metric_queue = metric_queue;
    g_diagnostics = diagnostics;

    Serial.begin(SERIAL_BAUD);

    // 蓝牙失败时 USB 仍保持可用，现场调试不会丢失全部诊断通道。
    const bool bt_ok = BTSerial.begin(
        BLUETOOTH_DEVICE_NAME
    );

    if (!bt_ok) {
        Serial.println(
            "#WARN,BluetoothSerial init failed; USB remains active"
        );
    }

    xTaskCreatePinnedToCore(
        transportTask,
        "PPG Transport",
        TRANSPORT_TASK_STACK,
        nullptr,
        TRANSPORT_TASK_PRIORITY,
        nullptr,
        TRANSPORT_CORE
    );
}
