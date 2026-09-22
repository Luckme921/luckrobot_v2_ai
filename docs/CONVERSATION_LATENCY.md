# 对话延迟改进

此分支以 Jetson release 源码快照为基础，保留音乐、音量和视觉功能。
没有替换设备上的生产目录。完整文本回答仍在生成完成后交给 TTS；
本次 /chat/events 只传进度和最终结果，不是正文 token 流。

## 路由

configs/agent.yaml 的 agent.route_protocol: json 使用 JSON object 输出。
程序校验 action、字段类型、范围、长度、完成状态，再复用现有动作解析。
非法或截断 JSON、接口不支持 JSON 时最多回退一次旧的强制工具路由；
网络和认证错误不触发协议回退。SDK 原有重试策略保持不变。
路由本身不执行动作；失败时不把原始模型输出当回答或动作使用。

route_protocol: tool 可以恢复旧路由。多模态已附图的快速路径、
本地身份权威回复、每轮最多一次联网搜索保持原有规则。

## 工具过渡语

agent_bridge.progress_enabled: true 让 Edge 使用 /chat/events（NDJSON）。
旧 /chat 保留；只有新端点返回 404/405 时，Edge 才重试旧端点。
流中断、工具失败等不重放请求，避免重复动作。
客户端断开会取消服务端协程；已在线程中开始的底层网络请求仍受自身超时控制。

工具确认后发送 tool_start；查询同时进行，不等待音频播完。
Edge 播放启动时缓存的短语，最多每轮一次：
搜索“我帮你查一下”、视觉“我看一下”、找音乐“我帮你找一下音乐”、
导航“我检查一下导航请求”。目前导航仍是 MOCK，过渡语不宣称执行成功。
普通聊天、音量、快速暂停/继续等不播放固定“思考”语。

tts.acknowledgement_delay_seconds: 0.35 为播放启动延迟。
结果先到则取消尚未开始的播报；已开始的短语在正式 TTS 前结束，
最多等待 4 秒后终止异常播放器。异常退出也会清理播放器。
tts.acknowledgement_enabled: false 可以完全关闭过渡语。
缓存音频生成发生在启动阶段，会增加首次启动时间，不增加每轮合成时间。
缓存音频与普通回复均使用 PulseAudio 当前设备音量。

## 计时

[TIMING] 是 JSON，含 trace_id、stage、seconds、可选 status。
[REMOTE_TIMING] 在 Edge 转发同一条 Cloud 记录，汇总时不要重复计算。
一个已识别回合中的视觉补图请求共用 trace_id。

- vad_buffer_after_segment：音频采样时钟上，已收到音频超出 VAD 语段末尾的长度。
- asr、capture_stop、vision_snapshot、identity、vision_select。
- memory_compact、memory_context、edge_http_chat。
- model_route_json / model_route_tool、model_answer / model_multimodal。
- tool_web_search / tool_navigate_to、tool_music、model_memory_compact。
- cloud_total、ack_drain、tts_first_callback、tts_total。
- turn_to_first_generated_audio：从 ASR 开始前到首批 TTS 音频生成。
- turn_until_reply_finished：从上述起点到普通 Agent 回合播报完成/错误清理。

各阶段存在包含和并行关系，不能直接相加。首批音频不等于扬声器实际出声；
这些指标也不包含精确声学断句时间。过渡语不算正式回答的首批音频。
原有 [LATENCY] 日志保留，但它的 agent_to_voice 不是完整端到端延迟。
本次未改变 VAD 参数，也未将人脸识别或记忆压缩移出同步路径，先通过计时评估。

## 验证与使用

Windows 本地回归：.venv\Scripts\python.exe -B -m unittest discover -s tests -q。
Jetson 回归：python -B -m unittest discover -s tests -q。
路由实测：python -m scripts.benchmark_routing --runs 3；
可加 --quick 只测普通问句。该脚本会调用付费模型 API，
但只返回路由、不执行查询、播放或导航、不写对话记忆。

设备验证请使用独立工作目录，配好模型、.venv、.env、private/faces；
不要覆盖带未提交修改的现有 release。确认测试与配置后再选择切换运行版本。
真实麦克风到扬声器的端到端延迟和音乐共存听感仍需设备验收。

## 本轮验证结果（2026-09-18）

- Windows Python 3.11：157 项 unittest 通过。
- 62 个 Python 文件通过 Python 3.10 语法检查；git diff --check 通过。
- Jetson Python 3.10：将本分支路由代码加载到独立进程内存中，
  使用设备原有配置与 API Key 测试；未写设备文件，未执行所选工具。
- 六个路由样例覆盖普通聊天、知识、天气、视觉、音乐、导航，两种协议均 6/6 正确。
  工具路由中位数 3.996 秒，JSON 路由中位数 0.909 秒。
- 同一普通问句交替各测三次：
  工具路由 4.1000 / 3.8312 / 3.8045 秒；
  JSON 路由 0.9199 / 0.9703 / 0.9545 秒。
  中位数从 3.8312 秒降至 0.9545 秒，减少约 75%。
- 这些是小样本路由测试，不代表完整声学端到端延迟。
  生产程序尚未切换，也未实测新的过渡语扬声器听感。
- 顺带修复 SQLite 连接只提交事务、不确定性关闭的问题；
  Windows 临时数据库清理和原有记忆回归测试已通过。

## 2026-09-19 状态日志与首音等待修复

音乐开始播放后 finally 根据 InteractionGate 实际状态输出日志，休眠时不再打印 LISTENING，而是 Waiting for "Lucky"。用户结束对话后也补充唤醒等待提示。

实测音乐候选回合：ack_drain=1.2669 秒，tts_first_callback=1.879 秒；旧链路先等待过渡语结束再合成，文本返回后额外串行等待约 3.15 秒。现在 TTS 在主线程合成，播放线程先等待过渡语结束，再提交正式音频，因此等待可重叠；不是强行截断过渡语或混音。收益需现场复测，不宣称固定降低到某个数值。

新增 tts_first_pcm_submit：从播放阶段初始化到首次向 pacat 提交 PCM 的时间，含过渡语等待；它不是扬声器声学首音，也不同于 tts_first_callback（合成开始至首次音频回调）。线程继承 trace_id，使两个指标可对应同一回合。

现有 Kokoro 样例 generation=7.988 秒、audio=7.503 秒，生成速度略慢于实时，可能导致供音不足的停顿。更换云端流式 TTS 可同时评估首音延迟与表现力，但网络延迟、音色和指令控制需要同文本试听；尚未更换默认引擎。

在线候选：阿里云 Qwen3-TTS-Instruct-Flash-Realtime，支持流式输入输出和指令控制。文档：https://help.aliyun.com/zh/model-studio/realtime-tts-user-guide 。开源候选：FunAudioLLM/CosyVoice，https://github.com/FunAudioLLM/CosyVoice 。不应把发布方服务器延迟当成 Jetson 8GB 实测性能。下一步在线对照需在设备 .env 配置对应服务的 Key，密钥不要发到聊天。

## Edge 晓晓主力与 Kokoro 回退

configs/audio.yaml: tts.provider=edge，edge_voice=zh-CN-XiaoxiaoNeural。改回 provider=kokoro 可恢复原离线路径。Kokoro 仍在启动时加载并生成工具过渡语缓存；正常回答由 Edge 提供，所以过渡语和最终回复可能音色不同。

edge_online.py 管理流式播放与回退；edge_worker.py 使用独立 Python 环境的 edge-tts 7.2.8，把 MP3 经 GStreamer 解码为 24kHz 单声道 s16le PCM；主进程持续写入 pacat，不等完整文件下载。edge_python 当前为 private/tts-eval-venv/bin/python，设备已有该环境；迁移设备须创建独立环境并安装 edge-tts==7.2.8，准备 gst-launch-1.0 的 mpegaudioparse、mpg123audiodec、audioconvert、audioresample、fdsrc/fdsink 和 pacat。

首批解码 PCM 超时默认 8 秒，后续无数据默认 10 秒，总轮次上限 120 秒（检查点限制）。未向播放器提交 PCM 时失败才转 Kokoro；一旦尝试提交就禁止整句重播，避免重复讲话。回退会增加首音等待。网络合成在子进程进行，可与过渡语等待重叠；正式 PCM 提交前仍等待过渡语结束。

计时 edge_first_decoded_pcm 包含进程启动、在线请求和解码；tts_first_pcm_submit 是向播放器提交首批 PCM 前的时刻，不是声学首音。Edge TtsResult 的 generation_seconds 包含网络与播放反压，不应把其 RTF 与离线纯推理 RTF 比较。当前不单独统计网络首包。

在线失败日志只显示异常类型，不写回复内容或带参数的音频地址。运行 Edge 时回复文本会发给微软在线语音服务。历史对话不会整批发送。

## 固定短句音色统一（2026-09-20）

工具过渡语和简单唤醒回应改为优先使用预先生成的 Edge 晓晓 WAV 缓存；准备脚本及验收见 OPERATIONS.md。缓存有效时现场没有合成/下载等待。缺失缓存只在启动阶段使用 Kokoro 兜底，日志可区分。普通回复仍采用 Edge 流式与 Kokoro 回退，尚未切换端到端语音模型。


## Lucky 伪全双工试用（2026-09-21）

最初版本只覆盖最终回复 TTS；2026-09-22 已由下一节所述的 THINKING 到 SPEAKING 全回合监测取代。普通 ASR 仍不并行，也不保证保留紧跟 Lucky 的命令；这不属于带 AEC 的真正全双工。

## 思考打断与正文流式 TTS（2026-09-22）

Lucky KWS 监测范围扩展为身份处理、Cloud 请求、正文流式合成和最终播报。检测到 Lucky 会关闭 Edge 当前 HTTP 响应、触发 Cloud `/chat/events` 断连取消并丢弃未完成结果；已经开始的外部工具副作用不能撤销，因此本地工具执行前会再次检查取消状态。`interaction.wake.record_interrupted_turns` 默认 true：只有 Cloud 尚未返回完整回复、记忆尚未落库时，保存用户输入和“输出被 Lucky 打断”的标记；关闭后不记录该回合。完整回复已返回后再打断播报，保留原完整回复，不另写中断标记。

`agent.stream_text_enabled` 让 GLM 最终文本回答使用供应商流式接口，并通过 `/chat/events` 发送 `text_delta`；JSON 路由仍等待完整 JSON。`agent_bridge.stream_text_to_tts` 让 Edge 按逗号、顿号、分号、句号、问号、感叹号及英文对应符号切分，依次提交给晓晓。两项均默认 true，可分别回退。普通文字回答和工具执行后的最终文字支持该链路；多模态首轮可能包含工具调用，仍采用完整响应。分段会更早出声，但每段单独建立 Edge TTS 请求，停顿和整体韵律需设备实测。
