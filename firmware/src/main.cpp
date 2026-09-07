#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>

#include "acquisition.h"
#include "config.h"
#include "data_types.h"
#include "diagnostics.h"
#include "transport.h"

namespace {

QueueHandle_t sample_queue = nullptr;
QueueHandle_t beat_queue = nullptr;
QueueHandle_t metric_queue = nullptr;

Diagnostics diagnostics;

bool createQueues() {
    // FreeRTOS 队列存储定长 POD 结构，不做动态字符串分配。
    sample_queue = xQueueCreate(SAMPLE_QUEUE_LENGTH, sizeof(SampleFrame));
    beat_queue = xQueueCreate(BEAT_QUEUE_LENGTH, sizeof(BeatFrame));
    metric_queue = xQueueCreate(METRIC_QUEUE_LENGTH, sizeof(MetricFrame));

    return sample_queue && beat_queue && metric_queue;
}

} // namespace

void setup() {
    // 队列必须先于两个任务创建。
    // 如果内存不足，使用 USB 串口给出明确故障信息后停在此处。
    Serial.begin(SERIAL_BAUD);

    if (!createQueues()) {
        Serial.println("#FATAL,FreeRTOS queue allocation failed");
        while (true) {
            delay(1000);
        }
    }

    // 传输任务在 Core 0；采集任务在 Core 1。
    // 启动后 main loop 不再参与 PPG 采样和输出。
    startTransportTask(
        sample_queue,
        beat_queue,
        metric_queue,
        &diagnostics
    );

    startAcquisitionTask(
        sample_queue,
        beat_queue,
        metric_queue,
        &diagnostics
    );
}

void loop() {
    // Arduino loopTask 只保留为空闲壳。
    // 核心业务全部由明确绑定核心的 FreeRTOS 任务管理。
    vTaskDelay(pdMS_TO_TICKS(1000));
}
