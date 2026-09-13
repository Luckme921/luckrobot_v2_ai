# LuckRobot AI

LuckRobot 是由 **哔哩哔哩 UP主 luckme** 开发的家用移动服务机器人。

本仓库是 LuckRobot 的 **Interaction / AI Jetson** 软件工程，负责语音交互、Cloud Agent、工具调用、本地 TTS、长期对话记忆，以及后续视觉与 ROS2 AI Gateway。

> 当前硬件平台：Jetson Orin Nano Super 8GB  
> 当前系统：JetPack 6.2.1 / Ubuntu 22.04 / Python 3.10

## 当前状态

截至 2026-09-13：

- Local SenseVoice ASR：完成
- Silero VAD 实时语音分段：完成
- Lucky KWS 唤醒与连续会话：完成
- Cloud GLM Agent：完成
- Tool Router：完成，导航仍为 MOCK
- 持久长对话记忆：完成
- Kokoro 本地 TTS：完成
- Controlled Web Search：完成
- 多声学变体 Lucky KWS：完成
- 实际 ROS2 导航接入：暂缓
- 本地常驻紧急停止：待导航阶段恢复后继续

## 当前语音架构

V1 使用半双工：

LISTENING → THINKING → SPEAKING → LISTENING

当前链路：

USB Mic  
→ Silero VAD  
→ Lucky KWS  
→ SenseVoice ASR  
→ Cloud Agent  
→ Tool Router / Web Search  
→ Kokoro TTS  
→ USB Speaker

## Web Search

实时互联网搜索已经通过智谱 Web Search 接入。

当前策略：

- 仅在最新、今天、近期、新闻、热点等时效性问题中使用
- 每个用户回合最多一次真实 Web Search 请求
- 普通常识问题不搜索
- 音乐搜索与播放未来使用独立工具

## Safety

导航相关开发当前暂停。

AI Jetson **绝不能直接发布原始 `/cmd_vel`**。

未来实际运动只能通过高层 ROS2 Action / Service 与 Navigation Jetson 协作，并且在接入真实运动前必须具备独立于 Cloud Agent 的本地安全停止机制。

## Repository Layout

- `cloud/`：Cloud Agent / Tool Router / Web Search
- `configs/`：Robot、Agent、Audio、KWS 配置
- `docs/`：完整开发状态和工程记录
- `edge/`：AI Jetson 本地运行时
- `scripts/`：启动和辅助脚本
- `tests/`：回归测试

## Detailed Project State

完整硬件配置、阶段记录、性能数据、验证结果和当前开发任务：

[docs/PROJECT_STATE.md](docs/PROJECT_STATE.md)

该文件是项目持续开发时的详细状态源，README 只保留最新总体概览。
