# 屏幕显示规划

## 推荐边界

第一版采用本机轻量 Web UI：机器人进程发布结构化显示事件，独立 FastAPI/静态页面负责渲染，Jetson 上 Chromium 使用 kiosk 模式全屏打开。显示进程故障不能阻塞音频、导航或工具执行；UI 只能发送白名单交互事件，不能构造 shell 命令或直接控制底盘。

建议状态：sleeping、listening、transcribing、thinking、speaking、interrupted、music。页面包含常驻表情/眼睛、最近一轮用户与机器人文字，以及音乐封面、歌名、歌手、播放状态。正文流式事件可以逐步更新字幕；音乐只展示供应商返回的元数据和本地播放状态。

## 可参考的开源项目（调研于 2026-09-22）

- RobotFace：浏览器 Paper.js 动画脸，Socket.IO 控制 emotion、talking、message 和视线，结构与本项目最接近，可借鉴状态协议和动画，不建议直接沿用其旧 Node 工程。https://github.com/webbo89/RobotFace
- Luna：Python/Pygame 的完整机器人助手，已有多种表情、说话嘴型和睡眠动画，可参考状态到表情的映射。它还包含自身 ASR/LLM/TTS，不能整体并入现有运行时。https://github.com/michaelharold/Luna
- RoboEyes：线程安全眼睛动画和 REST 控制，适合小 OLED；全尺寸 HDMI 屏只能借鉴眼睛状态机。https://github.com/sachinthra/robo_eyes
- Vizij：浏览器/原生/无头三种渲染、表情与 viseme 能力完整，适合未来 3D 脸和口型同步；Rust、GLB 和行为图的引入成本高于第一版。https://github.com/vizij-ai/vizij-rs
- MagicMirror²：成熟的 Electron 模块化信息屏，可参考模块布局；作为常驻机器人表情前端偏重。https://github.com/MagicMirrorOrg/MagicMirror
- Robotics UI 与 Foxglove 更适合 ROS 2 运维、地图和遥测，后续可作为工程师页面，不适合作为面向用户的主表情屏。https://github.com/sciotaio/robotics-ui 和 https://docs.foxglove.dev/docs/getting-started/frameworks/ros2

OpenVoiceOS 的现有 GUI 文档明确将旧 GUI 标为 deprecated、替代方案仍在重建，本项目暂不基于它开发。

## 实施顺序

1. 在 Jetson 确认屏幕分辨率、旋转、触摸能力、X11/Wayland 会话和 Chromium GPU 表现。
2. 定义只含语义状态的 `DisplayEvent`，由音频运行时发送，UI 不读取日志文件。
3. 实现 HTML/CSS/Canvas 表情、对话字幕与音乐卡片，Windows 浏览器先调试。
4. 增加本机 WebSocket/SSE 和断线后的 idle 回退，再配置 kiosk 自启动。
5. 现场测试音频优先级、GPU/CPU 占用、断网、屏幕拔插和进程崩溃隔离。
