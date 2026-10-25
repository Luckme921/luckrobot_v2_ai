# 多工具调用、错误定位与唤醒调试

2026-10-24。开发分支：codex/tool-batch-diagnostics。

## 多工具执行链路

用户原话 → 模型 route_turn → 单动作或 tool_batch → Cloud 返回 tool_requests →
Edge 完整校验整个计划 → 按资源分组执行 → 汇总真实结果并记入一次会话历史。

“帮我播放一首歌，并把风扇灯光调为蓝色呼吸灯”的路由示例：

```json
{"action":"tool_batch","actions":[
  {"action":"play_music","music_query":"随便"},
  {"action":"fan_light_control","fan_light_action":"set_light",
   "fan_light_mode":"breath","fan_light_red":0,"fan_light_green":0,"fan_light_blue":255}
]}
```

- 上限4个动作。音乐与风扇灯光独立并发；同一串口上的多个动作串行。
- 音乐和音量共用 audio 分组，按计划顺序执行，避免相互争用音频控制。
- 相互依赖的音乐“搜索后选第一首”不能作为两个并发动作，整批拒绝。
- 单项失败不掩盖其他项的成功，分别保留状态。
- Lucky 打断后尚未开始的操作跳过，正在进行的外部操作不能保证撤销。
  已完成的批次结果保存到历史；本版仍需等待在途调用返回。
- 天气、网页搜索、模拟导航通过本机 /tools/execute 调用 Cloud 工具；
  接口限制固定工具名并校验参数，不接收任意 URL 或 shell。
- 复合话语跳过单一音乐/音量快捷路径，由模型判断完整动作。
- 视觉采集、普通回答和结束对话不放进并发批次，保持单动作流程。
- 音乐播放前仍结束过渡语。音乐播放成功时不将最终 TTS 叠在歌曲上；
  其他动作的结果写入会话日志、历史与显示状态。需要语音查询结果时可单独询问。

重点文件：robot_tools/catalog.py（模型契约）、cloud/agent/client.py（计划解析）、
robot_tools/batch.py（资源分组与结果汇总）、edge/audio/runtime.py（执行和历史）。

## 模型失败定位

旧日志在 HTTPException 外层只打印 unavailable，丢失了上游具体错误类型。
2026-10-24 的多次失败是 model_route_json 成功后 model_answer 失败；
仅凭旧日志不能判定额度、网络或内容检查是哪一种。

现在 AGENT_ERROR 打印 trace_id、stage、异常类型、HTTP状态、provider code 和
request_id；不打印密钥、完整请求或供应商错误正文。播报区分额度不足、限流、
认证、网络、超时、内容拒绝、参数与响应问题。不会自动重放已经开始播报的流式
请求，也不会绕过供应商内容检查。原 SDK 重试配置保持不变。

历史复现未完成：将本地私密会话重新发送给外部模型的诊断被自动审批拒绝。
通过无历史的新测试语句验证链路，并用新增脱敏日志定位后续实际失败。

## 天气链路

get_weather → Open-Meteo 地名解析 → 唯一地点确认 → 预报查询 → 回复。
新增 weather_geocoding、weather_forecast 计时和 WEATHER_HTTP、WEATHER_ERROR。
网络超时、连接错误和临时 HTTP 状态最多重试一次，每次超时5秒；
非法响应和普通4xx不重试。同名地点仍要求用户补充地区，不擅自选择。

路由 city=深圳、weather_region=广东 → 工具 city=深圳、region=广东。
用户说“广东省深圳市”时模型应拆分城市和省份。
2026-10-24 修复前实测广州地名和预报均成功；深圳返回多个同名地点，属于
needs_input。10月17日广州失败的底层原因没有旧日志记录，无法追溯确认。

## 误唤醒处理

2026-10-24日志有18次睡眠KWS命中，其中NAKE 7次、NAKEYI 5次。
这不等于12次全都已人工确认误唤醒，但正常讨论中多次命中了这两个词条。
移除 n à k ě、n à k ě y ǐ 两项声学近音；保留 Lucky、LuckyLu、LuckyLucky
和其他实际使用的发音。暂不统一提高0.2阈值，避免叠加改变导致漏唤醒。
ASR转写清理别名不是声学词表，不需要一起删除。

下一步用相同麦克风的正负样本调参。以下命令只有手动执行才录音，
录音保存于private，不上传云端、不提交Git：

```bash
cd /home/jetson/luckrobot_latency_test
# 15秒内说Lucky/LuckyLu/LuckyLucky，变换距离和音量。
.venv/bin/python -B scripts/wake_diagnostics.py record --seconds 15 --output private/wake-eval/positive-01.wav
# 正常聊天负样本；也可另录音乐或机器人播报，并标记其中是否含真实唤醒词。
.venv/bin/python -B scripts/wake_diagnostics.py record --seconds 60 --output private/wake-eval/negative-01.wav
.venv/bin/python -B scripts/wake_diagnostics.py evaluate private/wake-eval/*.wav --thresholds 0.2 0.25 0.35
```

录音使用audio.yaml的设备与通道，输出单声道PCM16/16kHz。禁止覆盖同名样本。
评估只回放音频给KWS，不调用模型或执行设备动作。可用 --keywords-file 指定
另一个词表对照；比较误触发和漏检，不能只用单个样本选择阈值。
短唤醒词与回声问题不能靠增加文本别名根除；有足够正负样本后再考虑训练
专用唤醒模型或增加二次声学验证。

## 验证

自动测试覆盖独立资源并发、同资源顺序、整批预验证、部分失败、取消待执行项、
端云协议、天气地区消歧和重试边界。音乐加灯光的实物效果与误唤醒率需现场验收。
