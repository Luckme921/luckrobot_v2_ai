# Jetson 启动、测试与维护

2026-10-03 现场验证：更新后运行 `.venv/bin/python scripts/cache_tts_phrases.py` 生成新增的视觉过渡语及音乐歌手模板片段，再启动机器人。说“有没有张学友的歌，推荐一首给我听”，观察 `[ACK] SELECT` 和 `[ACK] PLAY mode=contextual`；如果显示 `mode=cached` 或 `DYNAMIC_FALLBACK`，说明本轮使用固定晓晓短句。说“现在不晚了，我打算要睡觉了”，确认日志有 `[ROUTE] action=end_conversation`、完整 `[AGENT_REPLY]`、播报后 `[STATE] SLEEPING reason=model_end_conversation`。说话跨越原来 8 秒唤醒等待或 12 秒追问等待时，应在 VAD 完成后才处理片段；`[GATE] IGNORE reason=wake_echo_fragment` 用于检查误识别唤醒残片。缓存和日志在 `private/`、`logs/`，不要提交。

2026-10-01 更新：`interaction.wake.include_pre_wake_speech` 默认为 `false`。KWS 后首段 ASR 若识别到位于句中的唤醒词，默认只处理唤醒词后的内容；设为 `true` 则保留整段。ASR 没有转写出唤醒词时无法可靠确定切分点，现场应核对 `[ASR_TEXT]`、`[COMMAND]`。过渡语和告别语增加了缓存短句，部署后运行 `python scripts/cache_tts_phrases.py` 为晓晓生成新缓存；若缓存缺失，启动时会尝试本地 Kokoro 合成。测试命令为 `.venv/bin/python -B -m unittest discover -s tests -q`，并检查 `git diff --check`。QQ 自动换曲的屏幕显示还需设备现场验收。

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

## 对话调试日志（2026-09-22）

`interaction.conversation_log.enabled=true` 写入 `logs/conversation.log`，单文件 2MB、保留三份轮转。事件包括 KWS 实际命中值、ASR 转写、最终用户命令、完整模型/本地工具回复和被 Lucky 打断的输入。主日志同时由 `debug_log_transcript=true` 打印 `[ASR_TEXT]`；睡眠诊断转写使用 `[ASR_SLEEP_TEXT]`。

    tail -f logs/conversation.log

`log_sleeping_asr=true` 会在等待 Lucky 时对 VAD 语段运行本地 SenseVoice，以便查看 KWS 未命中时“Lucky”被转写成了什么；这些文本只写日志，不能唤醒、进入记忆或执行命令。它会增加待机 CPU 使用，也会在本地日志记录环境讲话；排查结束可设为 false。日志、录音和 private 数据不得提交 Git。增加 KWS 声学变体时修改 `configs/keywords_lucky.txt`，增加唤醒后 ASR 文本清理别名时修改 `transcript_aliases`，两者用途不同。当前词表随运行项目加载，含两音节 `lucky`、三音节 `luckylu`、四音节 `luckylucky`；VAD 断句静音阈值为 0.4 秒。部署后分别口述三种发音并核对 `[KWS]` 与后续 `[ASR_TEXT]`，确认单独唤醒不送模型、带指令唤醒仅处理后面的指令。声学识别率仍需现场实测。


## Lucky 伪全双工试用（2026-09-21）

`interaction.wake.barge_in_enabled: true`（configs/audio.yaml）开启回复 TTS 合成/播报期间的 Lucky 检测；关闭即可恢复原半双工。需要同时启用 wake。正常 ASR 仍暂停，仅独立采集线程运行 KWS；检测到 Lucky 后终止本轮播放器，Kokoro 在下次合成回调停止，Edge 不会因主动打断而回退重播。清除歌曲候选，回到已唤醒等待命令状态。普通聊天和工具最终回复在 TTS 前已写入 SQLite，打断只影响播报，不删除已生成的完整回复，也不意味着用户听完了全文。

2026-09-21 初版只覆盖普通 Agent/工具最终回复；2026-09-22 已扩展到 THINKING。固定唤醒短句仍不能打断。音乐继续沿用已有 Lucky 暂停逻辑。先喊 Lucky，等声音停止后再说新命令；本版不缓存紧跟 Lucky 的命令，清理及原有 0.6 秒播放保护期间的语音可能丢失。不撤销已经开始或完成的工具操作。

这不是带 AEC 的真正全双工。机器人自己说出 Lucky 或环境播放唤醒词可能误触发；高音量可能降低检测率，需要现场验收。监测麦克风启动失败时打印 BARGE_IN UNAVAILABLE 并退回普通播报。日志中的 BARGE_IN 表示主动打断，不是 TTS 故障。

2026-09-22 起，同一监测器从 THINKING 持续到 TTS 结束。现场测试应覆盖：模型未返回时喊 Lucky，确认快速回到等待命令；检查历史只含用户输入和中断标记；将 `record_interrupted_turns` 临时设为 false 后确认不落库；长回复在第一个标点后开始合成；关闭 `agent.stream_text_enabled` 或 `agent_bridge.stream_text_to_tts` 后恢复整段回复。Cloud 断连取消依赖服务端感知连接关闭，底层供应商是否已经计费由供应商规则决定。

验收：请求长回答 → 播放中喊 Lucky → 停止播报 → 稍停后问新问题；确认前一轮完整回复仍在历史、没有重复存档、不会续播或触发 Kokoro 重播。另测普通讲话不打断、连续三轮打断、Kokoro 离线回退、机器人说出 Lucky 的误触发、音乐播放与结束对话。此功能当前仅本地代码及模拟测试完成，硬件效果未验证。
# 屏幕服务

`bash scripts/run_robot.sh` 现在统一监管 Cloud、Display、Audio 三个进程。
Display 使用本机端口 8765，日志写入 `logs/display-latency.log`；任一子进程退出，
supervisor 会停止其余进程。Jetson 图形桌面的 kiosk 浏览器需单独运行
`bash scripts/run_display_kiosk.sh`，现场确认 X11/Wayland 后再设置桌面自启动。
具体状态和演示入口见 `docs/DISPLAY.md`。

生产设备若不运行图形桌面，使用 `bash scripts/run_display_qt.sh` 以 linuxfb 直接输出。
linuxfb 会独占 framebuffer，启动前必须停止 GDM/X11。首次切换应保留 SSH 连接，以便渲染
失败时恢复 display manager。

`run_robot.sh` 只统一监管 Cloud、Display API 和 Audio，不启动直接访问 `/dev/fb0` 的
QML 渲染器。`linuxfb` 和内核 framebuffer console 共用 `/dev/fb0`；只停止 getty 或隐藏
光标不能避免 `console=tty0` 的日志覆盖。无桌面生产模式使用 systemd 独占显示服务：

```bash
cd /home/jetson/luckrobot_latency_test
sudo bash scripts/install_display_service.sh
systemctl status luckrobot-display.service --no-pager
journalctl -u luckrobot-display.service -f
```

服务与 `getty@tty1` 冲突，启动前把 framebuffer 类型的 vtconsole 从 `/dev/fb0` 解绑，
再以 `jetson` 用户运行 QML；停止服务时自动恢复 fbcon。串口控制台 `ttyTCU0` 和 SSH 不受
影响。脚本默认设置 `QT_QPA_FB_HIDECURSOR=1`，Qt 不绘制鼠标指针。检查 QML：

```bash
pgrep -af 'qmlscene.*edge/display/qml/main.qml'
```

恢复本地 tty 并移除开机显示服务：

```bash
sudo bash scripts/install_display_service.sh remove
```

不要通过 SSH 直接运行只有输入重定向的 `setterm ... < /dev/tty1`；`setterm` 会把控制序列
写到 SSH 客户端终端。若电脑终端光标因此消失，Linux/macOS/Git Bash 执行
`printf '\033[?25h'`，PowerShell 执行 `[Console]::CursorVisible = $true`。

当前 QML 是只读界面，不依赖触摸。需要触摸时，`jetson` 必须具有 `/dev/input/event*` 的
读取权限；可执行 `sudo usermod -aG input jetson` 后重新登录，不能把 input 设备改成全局
可写。

关闭桌面可临时执行 `sudo systemctl isolate multi-user.target`；用
`sudo systemctl set-default multi-user.target` 设置重启后的默认模式。恢复桌面时执行：

```bash
sudo systemctl set-default graphical.target
sudo systemctl isolate graphical.target
```

Jetson 当前的 `gdm.service` 是 static 单元，切换 target 即可，不需要单独 disable。切换
target 可能影响 PulseAudio，仍按下文检查 XVF3800 source/sink 与 `AUDIO_OK`。

Jetson 的 Qt 5 运行依赖为 `qmlscene`、`qml-module-qtquick2` 和
`qml-module-qtquick-window2`；启动脚本显式设置 `QT_SELECT=qt5`。

停止或重启 GDM 会使 PulseAudio 的 XVF3800 USB card 暂时消失。恢复桌面后执行
`XDG_RUNTIME_DIR=/run/user/1000 systemctl --user restart pulseaudio.service`，Audio
Runtime 会在 source/sink 重新出现后自动恢复到 `AUDIO_OK`。正式无桌面部署前需把
PulseAudio 作为独立用户服务验证，不能依赖 GDM 会话生命周期。

无桌面运行时，使用 systemd linger 保持 `jetson` 的用户管理器和 PulseAudio 在没有
GDM、桌面登录或 SSH 会话时继续运行：

```bash
sudo loginctl enable-linger jetson
systemctl --user enable --now pulseaudio.socket pulseaudio.service
```

配置只需执行一次，状态保存在系统中。检查开机配置和运行状态：

```bash
loginctl show-user jetson -p Linger -p State -p RuntimePath
systemctl --user is-enabled pulseaudio.socket pulseaudio.service
systemctl --user is-active pulseaudio.socket pulseaudio.service
pactl list short sources
pactl list short sinks
```

预期 `Linger=yes`，两个用户单元均为 `enabled` 和 `active`，并能看到 XVF3800 的
USB source/sink。项目按 USB 设备名称显式解析输入和输出，不依赖 ALSA card 编号或
PulseAudio 默认设备。手工运行 `systemctl --user` 无法连接时，SSH 会话中可显式加
`XDG_RUNTIME_DIR=/run/user/$(id -u)`；systemd 用户服务本身会在启动时创建运行目录。
