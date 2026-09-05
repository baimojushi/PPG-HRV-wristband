#pragma once

#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

#include "diagnostics.h"

// 采集任务的入口。
// zeezPPG 对象只在 acquisition.cpp 内部创建并访问，彻底取消原项目中
// “主循环写 + HRV 任务读同一个 PPG 对象”的互斥锁竞争。
void startAcquisitionTask(
    QueueHandle_t sample_queue,
    QueueHandle_t beat_queue,
    QueueHandle_t metric_queue,
    Diagnostics *diagnostics
);
