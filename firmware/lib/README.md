# 本地固件库

## zeezPPG

v0.3.0 起 PPG 检测算法完整保存在：

```text
firmware/lib/zeezPPG/src/
```

其中：

```text
zeezPPG.h/.cpp       Arduino / ADC / 滤波包装层
zeez_detector.h/.cpp 纯 C++ 动态检测核心
```

不再需要：

- Arduino IDE 全局库；
- PlatformIO `lib_deps`；
- 修改 `.pio/libdeps`；
- CheezPPG 自动补丁脚本。

重新安装系统、删除 `.pio`、换电脑都不会丢失算法源码。
