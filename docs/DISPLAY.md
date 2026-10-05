# 屏幕表情与对话显示

## 架构

音频运行时把结构化状态原子写入 `private/runtime/display_state.json`，独立的
Display 服务读取该文件并提供 `/api/state`。显示进程故障不会阻塞 ASR、模型、
TTS、工具或音乐播放。

Jetson 使用 Qt Quick/QML 渲染器。当前设备验证通过的路径为 Qt `linuxfb` 平台和
软件 scene graph，直接输出 `/dev/fb0`，不依赖 GNOME、X11 或浏览器。HTML/CSS
页面保留为 Windows 原型、远程调试和浏览器备用界面。两种渲染器共用相同状态协议。

支持状态：`sleeping`、`listening`、`transcribing`、`thinking`、`speaking`、
`interrupted` 和 `music`。界面显示最近一轮用户文字、流式模型回复、眼睛、眨眼、
嘴型和状态符号动画。

状态含义：`sleeping` 显示“等待 Lucky”，KWS 仍在听唤醒词；`listening` 显示
“我在听”或“等待下一句话”，麦克风/VAD 正在等待用户说完；`transcribing` 显示
“正在识别”，表示 VAD 已截出一段语音，SenseVoice 正把该段音频转文字；麦克风
进程可能仍采集 PCM，但这段处理期间不会开始另一条用户命令。`thinking` 显示
“想一想”或“正在处理音乐”，正在路由/调用模型或工具；
`speaking` 显示“正在回答”，TTS 正在播报；`interrupted` 表示 Lucky 打断了回复；
`music` 显示播放器曲目/歌词，唤醒词仍可用。空 ASR 或被忽略的唤醒残片会恢复
`listening`，避免画面长期停在“正在识别”。模型服务错误会显示并尽可能播报错误提示，
然后回到 `listening`；音频设备断开另有日志状态 `AUDIO_DEGRADED`，目前没有独立
的 QML 画面。

音乐播放状态显示程序化绘制的旋转唱片、装饰性均衡器动画、真实曲名和歌手。该均衡器
目前按 QML 动画参数运动，不读取 PCM 或 FFT，因此只表示“正在播放”，不代表真实频谱。
音乐工具通过 `display_state.json` 的 `music.title` 与 `music.artists` 传递元数据；停止
播放或播放器进程自然退出时清除该字段。睡眠状态下可选的 ASR 诊断只写对话日志，不再
覆盖 `music` 显示状态。QQ 网页播放器播放时，每 3 秒读取当前曲目及其专辑图片元素；
图片截屏原子缓存到 `private/runtime/music-cover.png`，状态中的 `music.cover_revision`
用于 `/api/music/cover?v=...` 防止旧曲封面串到新曲。QML 将封面裁成圆形放在旋转唱片内；
未取得图片、QQ 页面结构变化或其他音乐来源播放时保留原有图形。均衡器仍是装饰动画。
音乐状态隐藏通用“等待 Lucky”标题，只在独立底部区域显示正在播放信息，避免它与
曲名、歌手重叠；此时仍可使用 Lucky 暂停音乐并唤醒。

对话文字按停顿符号和显示宽度分行，局部滚动区同时显示上一行、当前行和下一行；当前行
字体较大，邻近行较淡。流式 TTS 每段开始/结束时推进当前行，长回复不再因每次新文字
到来而跳回顶部。非流式整段 TTS 只能标记开始和结束，尚无逐字播放时间戳；用户文字最多
显示两行，完整助手内容仍保存在显示状态和对话日志中。滚动区目前自动跟随，触摸手动
回看可在后续启用。

同一滚动组件用于音乐歌词：QQ 网页播放器若提供逐行歌词和当前行高亮，后台约每 1.5 秒
读取一次并显示相邻三行；网页不提供高亮或无歌词时保留曲名、歌手和唱片画面。此功能
读取 QQ 页面现有 DOM，不调用额外歌词 API；歌词刷新精度受轮询周期限制。

## 界面如何绘制与修改

当前生产界面不是一张整屏图片。`edge/display/qml/main.qml` 里的 `Rectangle`、`Text`、
`Repeater`、`Flickable` 和动画由 Qt Quick 实时计算位置与尺寸，再由 software scene graph
光栅化到 framebuffer：

- `Window` 与背景 `Gradient`：全屏画布和底色。
- `face`、`leftEye`、`rightEye`：按屏幕宽高比例计算的圆角矩形表情。
- `speakingAnimation`：回答时的嘴型缩放。
- `musicPanel`、`record`、`equalizer`：音乐唱片、旋转和律动区域。
- `lowerPanel`、`assistantViewport`：状态、正在播放信息和可滚动多行对话。
- 最后的 250 ms `Timer`：读取 `http://127.0.0.1:8765/api/state` 并更新 QML 属性。

修改颜色、比例、字体、间距、动画速度和布局，主要编辑
`edge/display/qml/main.qml`。修改状态字段或增加封面、歌词、播放进度时，同时修改
`edge/display/state.py`、`edge/audio/status.py` 和产生数据的音乐/音频运行时代码。修改
framebuffer 平台、软件渲染、触屏设备发现时编辑 `scripts/run_display_qt.sh`；修改开机独占
显示服务时编辑 `scripts/install_display_service.sh`。`edge/display/static/index.html` 只是
浏览器备用原型，不控制当前 Jetson Qt 直显界面。

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

默认平台是 `linuxfb`，默认 scene graph 为 `software`。它独占 framebuffer，不能与
正在运行的 X11/GNOME 同时使用。脚本通过 udev 属性动态查找触屏事件设备，不依赖
可能在重启后变化的 `/dev/input/eventN` 编号。

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

首次直显验收应保留 SSH 连接，并确认分辨率、屏幕旋转、字体、触摸坐标方向、
GPU 占用和显示进程异常退出后的恢复方式。验收完成后再配置 systemd 和禁用 GDM。

现场测试表明系统 Qt5 的普通 EGLFS 无法创建 OpenGL scene graph；显式选择
`eglfs_kms_egldevice` 时也无法打开 NVIDIA DRM 设备。因此当前不能把 EGLFS 宣称为
可用基线。未来若升级为适配 JetPack 的 Qt/NVIDIA EGL 集成，可通过
`LUCKROBOT_QT_PLATFORM=eglfs QT_QUICK_BACKEND=opengl` 重新测试。

## 设计参考

- [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)：LCD/OLED 表情与状态驱动机制。
- [xiaozhi-assets-generator](https://github.com/78/xiaozhi-assets-generator)：小智表情素材生成流程。
- [otto-emoji-gif-component](https://github.com/txp666/otto-emoji-gif-component)：MIT 许可的机器人循环表情。
- [xiaozhi-esp32-music](https://github.com/Maggotxy/xiaozhi-esp32-music)：MIT 许可的小智音乐固件，包含音乐与歌词显示思路。
- [dj-turntable](https://github.com/ltomuta/dj-turntable)：Qt Quick 唱片机和旋转动画示例。
- [Qt Embedded Linux](https://doc.qt.io/qt-6/embedded-linux.html)：linuxfb 与 software scene graph 的官方说明。
- [Qt Quick Text](https://doc.qt.io/qt-6/qml-qtquick-text.html)：多行换行与文本截断属性。

当前 CSS 和 QML 表情均为自行实现，没有复制上述项目的图片或代码。以后引入第三方
素材时需核对许可证并记录来源。
