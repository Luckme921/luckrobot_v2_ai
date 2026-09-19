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
