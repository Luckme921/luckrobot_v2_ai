# 项目结构与运行链路

更新：2026-09-19。主要测试目录：/home/jetson/luckrobot_latency_test。

## 从哪里启动

在项目根目录执行 bash scripts/run_robot.sh。入口 scripts/run_robot.py 先启动 cloud，健康检查通过后启动 audio；任一子进程退出时停止另一进程，Ctrl+C 一起退出。它不启动导航 ROS 栈。

- scripts/run_cloud.sh → cloud/api/main.py：本机 FastAPI，127.0.0.1:8000。名字 cloud 表示模型代理层，进程仍在 Jetson；GLM 请求才访问外部服务。
- scripts/run_audio.sh → edge/audio/runtime.py：麦克风、唤醒、VAD、ASR、会话状态、工具执行、TTS 和相机的编排入口。
- edge/audio/wake/session.py：休眠、唤醒与对话状态门控。
- edge/agent/cloud_client.py：请求代理、会话历史、进度事件接收。
- cloud/agent/client.py：JSON 意图路由、复杂任务模型调用和回复生成。
- robot_tools/：统一工具定义和函数实现；详见 TOOLS.md。
- shared/timing.py：分阶段计时与 trace_id。
- configs/：音频、视觉、工具配置；.env：本机密钥，不提交。
- tests/：回归测试；docs/：维护文档；logs/ 和 private/：运行数据。

## 一轮对话

音频采集 → 休眠时 KWS 检测 lucky → 唤醒后 VAD 切分 → ASR → 会话门控 → 本地音量/歌曲选择快捷处理或 JSON 路由 → 工具或模型回答 → TTS 合成播放 → 等待下一句话。

结束对话、停止聊天等完整命令在本地门控截获，不需要请求大模型；清除候选歌曲并回到休眠。休眠仍采集音频用于检测唤醒词，这是正常行为，不应继续响应普通讲话。当前不是全双工：正在合成/播放答复时不能保证立即接受口头打断。

## 哪些并行、哪些串行

cloud 与 audio 是独立进程；模型/工具进度通过 /chat/events 的 NDJSON 传输。工具过渡语由独立定时器和播放进程处理，可与网络工具请求重叠。相机采集、音频输入和外部播放器各有自身执行机制。

单轮主流程的 ASR、路由、工具结果处理、最终 TTS 仍有前后依赖。事件流不等于逐 token 文本流，也不等于逐句合成：不能把当前实现描述成完整流式语音对话。继续优化应使用 trace_id 分开比较 VAD 尾停顿、ASR、路由、工具、回复生成、TTS 首音等耗时。

导航模式 navigation_control 经本地Unix IPC接入独立rclpy桥接，ROS 2订阅监督/模式状态并调用固定Trigger。开机只订阅，显式任务可启动小脑idle栈；运动需屏幕确认。navigate_to目标阶段返回unsupported。协议、界面、CLI 和限制见 NAVIGATION.md。


声源方向接口 edge/audio/direction.py：音频进程内独立线程读取 USB DOA/VAD，提供 print 日志与 latest() 快照；与 ASR/LLM/TTS 并行，仅遥测，未接入导航。



## Lucky 伪全双工试用（2026-09-21）

最初版本只覆盖最终回复 TTS；2026-09-22 已由下一段的 THINKING 到 SPEAKING 全回合监测取代。普通 ASR 仍不并行，也不保证保留紧跟 Lucky 的命令；这不属于带 AEC 的真正全双工。

2026-09-22：独立 Lucky KWS 生命周期覆盖 THINKING 到 SPEAKING；取消令牌同时关闭 Edge HTTP 流和当前 TTS 子进程。最终正文路径为 GLM token stream → Cloud text_delta → Edge 标点缓冲 → 晓晓短句队列。对话路由、视觉/工具决定仍先完整校验，不能使用不完整流数据执行动作。该结构没有 AEC，也没有并行普通 ASR。

对话调试文本单独进入轮转的 `logs/conversation.log`，不混入简洁状态日志。睡眠 ASR 只是 KWS 调音旁路：`PCM → VAD → SenseVoice → debug log`，输出不会进入 InteractionGate。未来屏幕读取结构化状态/对话事件，不应解析终端日志；显示方案见 [DISPLAY.md](DISPLAY.md)。
# 本机显示边界

Audio Runtime 通过 `DisplayPublisher` 原子写入私有 JSON 状态；Display FastAPI
只读该状态并提供本机页面和 `/api/state`。UI 不解析运行日志，不向音频进程回写，
也不能执行工具、shell 或运动命令，因此显示服务故障不会进入控制链路。

当前设备渲染路径为 `QML → Qt Quick software scene graph → linuxfb → /dev/fb0`，
触摸输入通过 Qt evdev 插件进入 QML。系统 Qt5 的 EGLFS/NVIDIA DRM 路径现场测试
未通过，暂不作为生产基线。浏览器 UI 与 QML UI 都是只读状态客户端。
