# 屏幕表情与对话显示

## 架构

音频运行时把结构化状态原子写入 `private/runtime/display_state.json`，独立的
Display 服务读取该文件并提供 `/api/state`。显示进程故障不会阻塞 ASR、模型、
TTS、工具或音乐播放。

Jetson 推荐使用 Qt Quick/QML 渲染器：`qmlscene` 通过 EGLFS、EGL 和 OpenGL ES
直接输出到 DRM/KMS，不依赖 GNOME、X11 或浏览器。HTML/CSS 页面保留为 Windows
原型、远程调试和浏览器备用界面。两种渲染器共用相同状态协议。

支持状态：`sleeping`、`listening`、`transcribing`、`thinking`、`speaking`、
`interrupted` 和 `music`。界面显示最近一轮用户文字、流式模型回复、眼睛、眨眼、
嘴型和状态符号动画。

## 启动

完整机器人服务：

```bash
bash scripts/run_robot.sh
```

它会监管 Cloud、Display API 和 Audio 三个子进程。

无图形桌面的 Jetson 设备模式：先停止占用 DRM 的 display manager，再从本地 TTY
或 systemd 服务运行：

```bash
bash scripts/run_display_qt.sh
```

默认平台是 `eglfs`。EGLFS 独占显示设备，不能与正在运行的 X11/GNOME 同时使用。
当前触屏识别为 `/dev/input/event9`，脚本会在设备存在时配置 Qt evdev 触摸输入。

在当前 X11 桌面中调试 QML：

```bash
LUCKROBOT_QT_PLATFORM=xcb bash scripts/run_display_qt.sh
```

浏览器备用模式：

```bash
bash scripts/run_display_kiosk.sh
```

kiosk 脚本优先使用 Chromium，没有 Chromium 时回退 Firefox。仅启动状态服务可运行
`bash scripts/run_display.sh`，浏览器演示入口是
`http://127.0.0.1:8765/?demo=1`。

配置位于 `configs/audio.yaml`：

```yaml
display:
  enabled: true
  state_path: private/runtime/display_state.json
```

首次 EGLFS 验收应保留 SSH 连接，并确认分辨率、屏幕旋转、字体、触摸坐标方向、
GPU 占用和显示进程异常退出后的恢复方式。验收完成后再配置 systemd 和禁用 GDM。

## 设计参考

- [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)：LCD/OLED 表情与状态驱动机制。
- [xiaozhi-assets-generator](https://github.com/78/xiaozhi-assets-generator)：小智表情素材生成流程。
- [otto-emoji-gif-component](https://github.com/txp666/otto-emoji-gif-component)：MIT 许可的机器人循环表情。

当前 CSS 和 QML 表情均为自行实现，没有复制上述项目的图片或代码。以后引入第三方
素材时需核对许可证并记录来源。
