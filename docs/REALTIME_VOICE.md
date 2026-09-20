# 原生语音对话与工具调用评估

核对日期：2026-09-20。本轮为官方协议调查，未接入正式机器人、未上传现场录音，也未宣称完成端到端测试。

## 可行性

存在音频输入、音频输出并返回结构化函数调用的实时模型。模型只生成函数名与参数，应用仍需校验、执行 robot_tools 并回传函数结果；不能直接执行任意命令。原生音频可以减少独立 ASR→文本模型→TTS 的串行阶段，但网络、VAD 尾停顿、工具耗时和回声消除仍会影响体验，不保证固定延迟。

| 方案 | 官方协议已明确的能力 | 本项目建议 |
|---|---|---|
| GLM Realtime | WebSocket；音频/图片/视频输入，文本/音频输出；function_call 与 function_call_output；客户端/服务端 VAD | 优先做独立实验，与当前智谱账号体系相近，但要核实账号实时权限与计费 |
| Qwen-Omni Realtime | 官方实时接口说明包含 Function Calling；具体模型、地域和权限需按实时文档选择 | 中文语音候选，单独配置百炼凭据后对照 |
| Gemini Live API | 原生音频实时会话与函数调用；工具结果需显式发送 | 备选，先验证设备网络与账号可用性 |

## 下一步实验边界

先使用固定合成音频（问候、天气、点歌）做独立脚本实验，仅保存首音耗时、事件类型和 mock 工具调用结果；不控制麦克风、音箱、音乐或底盘。通过后才接入唤醒后音频，休眠期间不上传。先复用本地 VAD 手动提交完整回合，避免一次引入全双工回声问题。

测试必须包含：只有问候不调用工具；天气城市参数准确；工具调用 ID 去重；网络断开不重复动作；模型中断后取消过期调用；结束对话关闭本轮输入并回到 KWS。导航继续 MOCK。持久化会话记忆需另行设计，不能假定 WebSocket 断开会保留记忆。

## 官方资料

- GLM：https://github.com/MetaGLM/glm-realtime-sdk/blob/main/GLM-Realtime-doc-for-llm.md
- Qwen：https://help.aliyun.com/zh/model-studio/realtime
- Gemini：https://ai.google.dev/gemini-api/docs/live-api/tools

“端到端语音模型”与当前 /chat/events 进度事件流不同，也不是仅把 TTS 换为云端。新模型能否改善情感和工具准确率必须用本项目的中文样例试听和实测。
