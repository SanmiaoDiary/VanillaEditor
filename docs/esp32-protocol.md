# ESP-32 摆件通信协议规范

**版本**: 1.0  
**作者**: SanmiaoStudio (SanmiaoDiary)  
**日期**: 2026-11-21  

---

## 概述

本文档定义 VanillaEditor 与 ESP32 硬件摆件之间的数据同步协议。摆件用于展示写作激励信息，包括今日字数、累计字数、连续写作天数等，帮助用户保持创作热情。

---

## 硬件配置建议

### 推荐组件
- **微控制器**: ESP32-DevKitC 或 ESP32-S3
- **显示屏**: 
  - 选项 A: 1.54" 电子墨水屏 (Waveshare e-Paper HAT)
  - 选项 B: 0.96" OLED SSD1306 (I2C)
  - 选项 C: 2.0" IPS LCD (SPI)
- **电源**: USB-C 供电或锂电池 + TP4056 充电模块
- **外壳**: 3D 打印定制壳（设计文件见附录）

### WiFi 配置
首次使用时需通过手机端或浏览器配置 WiFi 凭据：
```json
{
  "ssid": "你的WiFi名称",
  "password": "你的WiFi密码",
  "server_host": "192.168.x.x",  // VE 服务器 IP
  "server_port": 58446,
  "username": "vanilla_user"     // VE 用户名
}
```
配置存储于 ESP32 SPIFFS/LittleFS。

---

## API 接口

### 主接口：拉取统计数据

**URL**: `GET http://<ve-server>:58446/api/esp/sync?username=<username>`

**参数**:
- `username` (必需): VE 用户名

**响应示例**:
```json
{
  "words_today": 1520,
  "words_total": 45670,
  "streak_days": 7,
  "last_updated": "2026-11-21",
  "files_created_today": 2,
  "status": "ok"
}
```

**错误响应**:
```json
{
  "error": "username required"
}
```

---

### 备选接口：完整 stats 数据

如需更详细数据（供多屏幕显示），可使用：
```
GET /api/stats?days=30
```
需要认证头：
```
Authorization: Bearer <token>
```
返回格式参见 [DESIGN.md §6 Stats API](../DESIGN.md)。

---

## ESP32 固件示例（Arduino/C++）

```cpp
#include <WiFi.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <Wire.h>

// === 配置 ===
const char* ssid = "YOUR_SSID";
const char* password = "YOUR_PASSWORD";
const char* serverHost = "192.168.1.100";
const int serverPort = 58446;
const char* username = "your_ve_username";

// === 显示屏初始化 (以 SSD1306 OLED 为例) ===
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

// === WiFi 连接 ===
void setupWiFi() {
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");
}

// === 拉取数据 ===
void fetchStats() {
  HTTPClient http;
  String url = "http://";
  url += serverHost;
  url += ":";
  url += serverPort;
  url += "/api/esp/sync?username=";
  url += username;
  
  http.begin(url);
  int httpResponseCode = http.GET();
  
  if (httpResponseCode > 0) {
    String payload = http.getString();
    Serial.println(payload);
    // 解析 JSON 并更新显示
    parseAndDisplay(payload);
  } else {
    Serial.print("Error: ");
    Serial.println(httpResponseCode);
  }
  http.end();
}

// === 显示逻辑 ===
void parseAndDisplay(String json) {
  // 简单解析（生产环境用 ArduinoJson 库）
  // 假设格式: {"words_today":1520,"words_total":45670,...}
  
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("VanillaEditor");
  
  display.setTextSize(2);
  display.setCursor(0, 20);
  display.println("Today: ---");
  
  display.setTextSize(1);
  display.setCursor(0, 40);
  display.println("Total: ---");
  
  display.display();
}

// === 主循环 ===
void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    fetchStats();
  }
  delay(300000);  // 每 5 分钟刷新一次
}
```

---

## 显示布局建议

### 方案 A：简约模式（OLED）
```
┌─────────────────┐
│  VanillaEditor  │
│                 │
│  今日: 1,520字   │
│  总计: 45,670字  │
│                 │
│  连续: 7天      │
└─────────────────┘
```

### 方案 B：详情模式（2.0" LCD）
```
┌──────────────────────┐
│  📊 写作激励站       │
│                      │
│  今日完成: 1,520 字  │
│  周目标: ████░░░ 70% │
│                      │
│  累计写作: 45,670 字 │
│  连续天数: 7 天      │
│  文件创建: 2 个      │
│                      │
│  最后更新: 11-21    │
└──────────────────────┘
```

---

## 数据刷新策略

| 场景 | 频率 | 说明 |
|------|------|------|
| 正常轮询 | 5 分钟 | 平衡电量与实时性 |
| 用户活跃时 | 1 分钟 | 可通过 BLE/NFC 触发 |
| 低电量模式 | 30 分钟 | 电池低于 20% 自动降频 |

---

## 功耗优化

1. **深睡模式**: 使用 `ESP.deepSleep()` 在两次请求间休眠
2. **屏幕刷新率**: 电子墨水屏仅在数据变化时刷新
3. **WiFi 管理**: 使用 `WiFi.disconnect(true)` 释放资源

### 深睡示例代码
```cpp
void goToSleep() {
  display.clearDisplay();
  display.setRotation(2);
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println("Zzz...");
  display.display();
  
  // 深睡 5 分钟
  esp_sleep_enable_timer_wakeup(5 * 60 * 1000000ULL);
  esp_deep_sleep_start();
}
```

---

## 安全注意事项

1. **网络隔离**: 建议在家庭局域网内运行，不暴露到公网
2. **凭据保护**: WiFi 密码和 VE 用户名不应硬编码进固件
3. **HTTPS 支持**: 如启用远程访问，建议使用 HTTPS 并禁用证书验证检查（仅限内网）

---

## 附录：3D 打印外壳设计要点

- 尺寸参考：ESP32-DevKitC (52mm × 27mm) + 显示屏
- 散热孔：顶部开孔辅助散热
- 固定方式：M2 螺丝孔位对齐 ESP32 安装孔
- 线缆出口：底部预留 USB-C 线出口

---

## 相关文档

- [VanillaEditor DESIGN.md](../DESIGN.md) — 系统架构设计
- [ESPressif ESP32 技术参考手册](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/)
- [Adafruit SSD1306 驱动库](https://github.com/adafruit/Adafruit_SSD1306)
