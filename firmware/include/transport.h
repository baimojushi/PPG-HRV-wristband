#pragma once

#include <Arduino.h>
#include <BluetoothSerial.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

#include "diagnostics.h"

// 初始化 USB / 经典蓝牙，并创建独立传输任务。
// 所有文本格式化都在该任务执行。
void startTransportTask(
    QueueHandle_t sample_queue,
    QueueHandle_t beat_queue,
    QueueHandle_t metric_queue,
    Diagnostics *diagnostics
);
