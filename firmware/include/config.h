#pragma once

#include <Arduino.h>

// ============================================================================
// 采集与兼容参数
// ============================================================================
// 125 Hz、GPIO32、10 bit ADC、Wear=1 保持历史工程一致。
// 11.0 在 v0.3.2 中是“兼容灵敏度中性点”，只小范围缩放综合评分门，
// 不再表示单一的 N×标准差心搏阈值。
constexpr uint8_t PPG_INPUT_PIN = 32;
constexpr uint16_t PPG_SAMPLE_RATE_HZ = 125;
// 历史 CSV 原始通道范围为 0–1023；显式固定 10 位 ADC，避免 ESP32 默认 12 位改变尺度。
constexpr uint8_t PPG_ADC_RESOLUTION_BITS = 10;
constexpr float PPG_SAMPLE_PERIOD_US = 1000000.0f / PPG_SAMPLE_RATE_HZ;

constexpr int PPG_WEAR_THRESHOLD = 1;
constexpr float PPG_PEAK_THRESHOLD_FACTOR = 11.0f;


constexpr uint32_t HRV_UPDATE_PERIOD_MS = 20000;
constexpr size_t HRV_WINDOW_RR_COUNT = 60;
constexpr size_t HRV_MIN_VALID_RR_COUNT = 40;

// ============================================================================
// 任务与队列
// ============================================================================
// 采集任务只处理 PPG 与时间戳；传输任务处理字符串格式化、USB、经典蓝牙。
constexpr BaseType_t ACQUISITION_CORE = 1;
constexpr BaseType_t TRANSPORT_CORE = 0;

constexpr UBaseType_t ACQUISITION_TASK_PRIORITY = 4;
constexpr UBaseType_t TRANSPORT_TASK_PRIORITY = 2;

constexpr uint32_t ACQUISITION_TASK_STACK = 6144;
constexpr uint32_t TRANSPORT_TASK_STACK = 6144;

// 512 个样本约等于 4.1 秒缓冲。
// 即便蓝牙短时间阻塞，采样任务也不会等待传输任务。
constexpr size_t SAMPLE_QUEUE_LENGTH = 512;
constexpr size_t BEAT_QUEUE_LENGTH = 64;
constexpr size_t METRIC_QUEUE_LENGTH = 16;

// ============================================================================
// 输出与质量标记
// ============================================================================
constexpr uint32_t SERIAL_BAUD = 115200;
constexpr const char *BLUETOOTH_DEVICE_NAME = "ESP32-PPG-Monitor";

// 历史 CSV 中原始 PPG 的有效上限表现为 1023。
// 这里只用于“饱和风险”质量标记，不参与原峰值检测算法。
constexpr int16_t QUALITY_ADC_LOW = 0;
constexpr int16_t QUALITY_ADC_HIGH = 1023;

// 新增 RR 硬异常范围。
// 该层只过滤明显不合理的搏间期，局部难异常由桌面端鲁棒清洗进一步处理。
constexpr uint16_t RR_HARD_MIN_MS = 300;
constexpr uint16_t RR_HARD_MAX_MS = 2000;

// 诊断帧频率。
constexpr uint32_t DIAGNOSTIC_PERIOD_MS = 5000;
