# 屏幕表情与对话显示

## 当前初版

显示系统采用独立的本机 Web UI。音频运行时只把结构化状态原子写入
`private/runtime/display_state.json`；显示服务读取该文件，浏览器每 250 ms
刷新一次。屏幕故障不会阻塞 ASR、模型、TTS、工具或音乐播放。

页面支持以下状态：

- `sleeping`：等待 Lucky，闭眼休眠
- `listening`：已经唤醒，等待用户讲话
- `transcribing`：语音转文字
- `thinking`：本地处理或模型思考
- `speaking`：流式显示回答，并播放说话动画
- `interrupted`：Lucky 打断
- `music`：音乐播放中

页面还显示最近一轮用户文字和机器人回答。UI 纯 HTML/CSS/JavaScript，
不依赖 CDN、图片或在线字体，断网后仍能显示。`?demo=1` 会自动轮播状态，
可在 Windows 浏览器中预览。

## 启动与预览

完整启动：

```bash
bash scripts/run_robot.sh
```

`run_robot.py` 会启动 Cloud、Display 和 Audio 三个子进程。显示服务只监听
`127.0.0.1:8765`。在 Jetson 图形桌面中另开终端运行：

```bash
bash scripts/run_display_kiosk.sh
```

仅调试显示服务：

```bash
bash scripts/run_display.sh
```

然后打开 `http://127.0.0.1:8765/?demo=1`。kiosk 脚本优先使用 Chromium，
设备未安装 Chromium 时回退到 Firefox。首次现场验收需确认屏幕分辨率、旋转方向、
浏览器命令以及 X11/Wayland 会话；确认后再配置桌面自启动。

配置在 `configs/audio.yaml` 的 `display` 节：

```yaml
display:
  enabled: true
  state_path: private/runtime/display_state.json
```

## 设计参考

- [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)：LCD/OLED 表情、状态驱动与素材机制。
- [xiaozhi-assets-generator](https://github.com/78/xiaozhi-assets-generator)：小智表情素材生成流程。
- [otto-emoji-gif-component](https://github.com/txp666/otto-emoji-gif-component)：MIT 许可的 240×240 机器人循环表情，可作为后续动态素材参考。

初版自行实现 CSS 表情，没有复制上述项目的图片或代码。后续若引入 GIF、封面或
第三方组件，先核对许可证并在仓库中记录来源。
