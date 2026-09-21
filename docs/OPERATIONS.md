# Jetson 启动、测试与维护

在 /home/jetson/luckrobot_latency_test 执行：

    bash scripts/run_robot.sh --check
    bash scripts/run_robot.sh

--check 只检查配置路径，不保证麦克风、模型、网络可用。正式启动先检查端口 8000，并用 private/runtime/robot.lock 防止本目录重复启动。旧 cloud/audio 仍运行时，先在原终端 Ctrl+C 停止，不能再启动第二套。

日志：logs/cloud-latency.log、logs/audio-latency.log；后台启动可把 supervisor 输出重定向到 logs/robot-supervisor.log。前台 Ctrl+C 停止两个子进程。后台可读取 private/runtime/robot.lock 内的 PID，先用 ps 确认是本目录的 scripts.run_robot，再 kill -TERM 该 PID；不要用宽泛 pkill python。

测试：

    .venv/bin/python -B -m unittest discover -s tests -q
    git diff --check

现场验收：喊 lucky → 普通问答 → 说结束对话 → 普通讲话不触发回答 → 再喊 lucky 可恢复。分别记录简单问答、天气、视觉的分阶段计时。天气必须指定城市。音乐启用前阅读 TOOLS.md；启用后点歌应该先播候选，再选择第一首开始音乐；喊 lucky 暂停音乐并恢复对话。

真实麦克风识别、音箱输出和运动不能由 mock 单元测试证明。当前 navigate_to 仍是 MOCK，统一启动器不会启动 ROS 导航。不要提交 .env、日志、私有记忆或音视频数据。

## 本次验证记录（2026-09-19）

182 项 unittest 通过，git diff --check 通过，统一启动 --check 通过。实际新进程日志显示 Kokoro、Lucky KWS、SenseVoice、相机、麦克风初始化成功，进入 SLEEPING / Waiting for Lucky。

真实 GLM JSON 路由：深圳天气 → get_weather（1.551 秒）；音量百分之三十 → volume_control set 30（0.838 秒）；播放第一首 → select_music（1.184 秒）。这些是单次路由耗时，非端到端语音延迟。未执行实际音量调整或音乐播放。

天气实测地理编码返回三个同名“深圳”，因此当前实现要求补充地区；天气预报成功仍未现场验证。用户语音唤醒、结束对话和真实扬声器播放仍需现场验收。

## 固定晓晓音频缓存与本地唤醒回应（2026-09-20）

部署后先执行 .venv/bin/python -m scripts.cache_tts_phrases。它只合成固定文本，不播放声音；每条最多等待 30 秒，已验证的缓存不重复下载，失败可重跑。缓存 private/tts-phrases 按音色、文本和格式哈希命名，以临时文件验证成功后替换。缓存不提交 Git，搬迁设备需要重新生成。

重启主程序后确认八条 [CACHE] EDGE_READY（五条工具过渡语、三条唤醒回应）。缺失/损坏时启动阶段回退本地合成并打印 LOCAL_FALLBACK，避免启动依赖外网；正常运行固定短句均直接本地播放。

现场验收：Lucky → 我在呢/你好呀/有什么想聊的吗；Lucky你好 → 本地回应；Lucky你好帮我查天气 → 原对话路由，不吞掉后续命令。只在刚唤醒等待命令阶段识别完整寒暄；已进入对话的“你好”按普通对话处理。每次唤醒最多回应一次；仍需 ASR 完整断句判断，非 KWS 检测到单词就立即打断用户。回答后保持等待命令，原唤醒超时仍生效。

当前仍半双工，本地短句播放期间不处理新讲话；多模态实时模型评估见 REALTIME_VOICE.md。音乐自动播放默认关闭，显式开启及歧义规则见 TOOLS.md。


## 声源方向日志

audio.sound_direction.enabled 控制 XVF3800 后台只读线程，日志前缀 [DOA]，默认每秒打印；安装依赖、USB 权限与前方标定见 SOUND_DIRECTION.md。不启动任何运动控制。声源方向日志与 USB 权限、配置说明见 [SOUND_DIRECTION.md](SOUND_DIRECTION.md)。


## 简洁状态视图（2026-09-21）

完整诊断日志保留，另写 logs/status.log（1MB轮转，保留两份备份），只显示等待 Lucky、已唤醒等待讲话、ASR、思考/模型处理中、本地音乐处理、已得到回复、speak、等待下一句等状态。连续相同状态去重。这是流水线状态而非精确声学出声时间。

    tail -f logs/status.log

Windows 阅读下载的日志可用 Get-Content logs/status.log -Wait。DOA 读取仍运行，但 audio.sound_direction.log_samples=false 默认不打印采样；接口错误只在错误变化时打印。临时查看实时方向仍可运行 python -m edge.audio.direction。
