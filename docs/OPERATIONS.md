2026-10-28晚间更新：明确语音导航任务直接执行，屏幕提供完整备用操作；显示改为轻量X11并支持本机RViz监视、刷新和返回。详见 [NAVIGATION.md](NAVIGATION.md)。

# 2026-10-28 更新：唤醒暂停音乐与底盘模式接口

已实现与验收边界见 [NAVIGATION.md](NAVIGATION.md)。旧阶段的 MOCK/暂缓导航记录保留作为历史，当前支持 ROS 2监督/模式桥接，语义地点和坐标目标仍未支持。开机只查询状态，不启动运动。

# Jetson 启动、测试与维护

2026-10-24：Cloud新增本机 /tools/execute，Cloud与Edge须一并部署。测试
“帮我播放一首歌，并把风扇灯光调为蓝色呼吸灯”，检查source=model_batch的
两条请求和各自TOOL_RESULT。错误看AGENT_ERROR的stage/reason/code；天气看
WEATHER_HTTP与WEATHER_ERROR。手动录音与回放步骤见[诊断文档](TOOL_BATCH_AND_WAKE.md)。

风扇灯光：在运行音频进程的 Jetson venv 中安装 `pyserial`，确认 `/dev/serial/by-id/` 下恰好存在一个 PWLINK2 或 CP2102 候选设备，且该用户可访问串口。当前 Jetson 实测 CP2102 对 `STATUS` 返回 STM32 风扇状态；程序也会核对状态签名后才写入默认值。接线修正后，启动状态目标为 `FAN1=50%`、`LIGHT=ON`、`MODE=BREATH`、`RGB=255,0,0`、`BRIGHT=20`。串口只能由音频进程独占，运行期间不要同时使用 `~/stm32_fan_ctl.py`。现场分别说“红色呼吸灯”“关闭风扇灯”“彩虹灯”并观察两只实体灯；状态回复不能代替实物验收。

独立手动调试：先 `sudo systemctl stop luckrobot_run.service`，然后运行 `.venv/bin/python scripts/fan_serial_manual.py status`。可依次运行 `release`、`bright 20`、`color 255 255 0`、`mode breath`、`light off`、`light on`。每次运行都先核对 STM32 的 `STATUS` 签名，输出命令原始回复与执行后状态。PWM 接线故障未排除前不要用 `speed`；若确需诊断，参数 `--allow-pwm speed 50` 必须放在子命令前，且需持续观察风扇是否停转。调试结束用 `sudo systemctl start luckrobot_run.service` 恢复服务。

## systemd 守护启动（测试目录）

使用 `deploy/systemd/luckrobot_run.service` 管理 Cloud、显示状态 API 和音频监督进程；Qt framebuffer 画面仍由 `luckrobot-display.service` 单独运行。音频使用 jetson 用户的 PulseAudio，会话路径须设置 `XDG_RUNTIME_DIR=/run/user/1000` 与 `PULSE_SERVER=unix:/run/user/1000/pulse/native`。unit 等待 PulseAudio 可连接后再启动程序；`ExecStop` 无需读取 `robot.lock`，systemd 会向服务进程组发送停止信号。启用前确保 `loginctl show-user jetson -p Linger` 显示 `Linger=yes`，且设备上没有手工启动的另一套监督进程。

安装或更新：`sudo install -m 644 deploy/systemd/luckrobot_run.service /etc/systemd/system/luckrobot_run.service`，然后 `sudo systemctl daemon-reload && sudo systemctl reset-failed luckrobot_run.service && sudo systemctl enable --now luckrobot_run.service`。查验：`systemctl status luckrobot_run.service luckrobot-display.service`、`journalctl -u luckrobot_run.service -b -n 80 --no-pager`、`tail -n 80 logs/audio-latency.log`。若云服务或音频子进程退出，监督进程会停止其余子进程，再由 systemd 按限速策略重启。

本地歌单功能验收：QQ 登录且 `private/qqmusic-library.json` 已同步后，依次说“播放我喜欢歌单”“下一首”“停止音乐”“推荐几首歌”“从我的歌单推荐三首”。检查 `logs/audio-latency.log` 的 `[MUSIC] PLAYLIST_START`、`PLAYLIST_ADVANCE`、`PLAYLIST_FINISHED`，并核对扬声器实际曲目与屏幕歌名。缓存缺失时先在屏幕完成 QQ 登录/检查，让 `library_refresh_on_login` 同步；不要把个人曲库复制进受 Git 管理的配置文件。

2026-10-05 百炼试用：在测试目录 `/home/jetson/luckrobot_latency_test` 的 `.env` 增加 `DASHSCOPE_API_KEY=你的北京地域百炼密钥`，不要提交 `.env`。当前模型配置是 `qwen3.8-max`，默认关闭原智谱 `web_search`。启动前可运行 `.venv/bin/python -B -m unittest discover -s tests -q` 和 `bash scripts/run_robot.sh --check`；启动后分别试普通问答、视觉请求、天气和点歌，核对 `logs/cloud-latency.log` 的路由与模型阶段。没有百炼密钥时 Cloud 首次请求会报 `DASHSCOPE_API_KEY is not configured`；单元测试不能证明账号权限、额度或设备语音链路正常。

2026-10-05 模型错误诊断：`[REMOTE_TIMING] model_route_json status=error` 后若显示/播报“大模型账户余额不足或没有可用资源包”，说明 GLM 上游返回了额度错误，需检查对应账户，不是麦克风、QQ 歌单或本地路由故障。Cloud 事件仅传 `quota_exhausted` 等有限原因，不传上游完整报错。若音频端仍停在“正在识别”，查看 `[ASR_TEXT]` 和 `[GATE] IGNORE`；空识别或被忽略的唤醒残片现在会把画面恢复为“我在听”或“等待下一句话”。

2026-10-05：音频进程启动后检查 QQ 音乐登录状态；若已登录，或屏幕扫码登录成功，`music.library_refresh_on_login: true` 会启动一次后台个人歌单同步。查看 `logs/audio-latency.log` 中的 `[MUSIC] PERSONAL_REFRESH_LOGIN_START` / `PERSONAL_REFRESH_LOGIN_OK playlists=... songs=...`；失败看 `PERSONAL_REFRESH_LOGIN_ERROR`。同步结果保存在 `private/qqmusic-library.json`，自动补充点歌路由的歌手/歌名词表，不写回 `configs/music_preferences.yaml`。首次同步可能占用共享 QQ 浏览器，结束后再测试语音点歌；退出登录会清除个人缓存。

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

当前 QML 的 QQ 音乐登录入口依赖触摸。`luckrobot-display.service` 已通过
`SupplementaryGroups=video input` 获得输入设备权限；首先确认触摸设备在 USB 和
`/proc/bus/input/devices` 中出现，再重启服务。不要把 input 设备改成全局可写。

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
# QQ 音乐重新登录（无图形桌面）

启动 `bash scripts/run_robot.sh` 和独占屏幕服务后，触摸屏幕左上角“QQ 音乐登录”。屏幕显示完整 QQ 登录网页画面；在网页中选择登录方式，用手机 QQ 扫网页二维码并确认。网页预览约每秒刷新，触摸会转给后台 Firefox。登录成功后再试歌曲搜索。若网页二维码过期，关闭并重新打开登录入口；账号状态和网页截图只保存在 `private/runtime/`。`[MUSIC] PREWARM webdriver-ready` 仅表示浏览器启动，不是登录成功。可通过 `curl -s http://127.0.0.1:8765/api/music/auth` 查看认证状态，不要复制或提交网页登录截图、Cookie、Firefox profile。

2026-10-03 屏幕布局更新：QQ 音乐登录入口位于左上角，显示服务未连接提示位于顶部中间。Qt 启动日志会打印 `[DISPLAY] touchscreen=/dev/input/eventN` 或 `touchscreen=missing`。HDMI 只传画面，触摸还需要 USB 数据线；若启动时未识别触摸屏，检查 `lsusb`、`/proc/bus/input/devices` 和 `udevadm info --query=property --name=/dev/input/eventN`，接好线后重启 `luckrobot-display.service` 让启动脚本重新选择触摸设备。服务配置需要 `SupplementaryGroups=video input` 才能读取 framebuffer 和输入设备。

触摸暂不可用时，可在 Jetson SSH 上运行 `curl -X POST -H 'X-LuckRobot-Display: 1' http://127.0.0.1:8765/api/music/auth/login`。生成二维码后，Qt 会自动打开扫码面板；该接口仅监听设备本机的 `127.0.0.1`。

认证入口会先检查网页会话；账号仍在线时状态变为 `ready`，不显示二维码。Firefox 使用项目私有配置目录直接运行，重启机器人后应保持登录。若状态为 `error`，先看 `GET /api/music/auth` 的 `detail` 所列网页阶段，再看 `logs/audio-latency.log` 中的 `QQ_AUTH_ERROR`。触摸未在 `lsusb` 和 `/proc/bus/input/devices` 中枚举时，屏幕点击本身不能触发请求，应先排查屏幕的 USB 触控线；可暂用上面的本机接口触发。

2026-10-04：机器人主进程启动后异步检查 QQ 音乐登录状态；`GET /api/music/auth` 返回 `state`、网页昵称 `nickname` 和本地头像可用标记 `avatar`。屏幕左上角已登录入口可查看账号、退出登录或切换用户；退出会停止专用 Firefox 播放器并清除该项目 profile 的 Cookie，切换会继续生成新二维码。触摸硬件未枚举时可从 Jetson 本机执行 `curl -X POST -H 'X-LuckRobot-Display: 1' http://127.0.0.1:8765/api/music/auth/logout`；随后再次调用 `/api/music/auth/login`。不要在检查运行状态时清空 `private/`，其中包含登录会话与备份。若只启动 `luckrobot-display.service`，`8000` 的 Cloud/Audio 主进程不会自动启动，应另外执行 `bash scripts/run_robot.sh` 并检查 `private/runtime/robot.lock` 和 `logs/robot-supervisor*.log`。

网页登录预览沿用当前无桌面 `linuxfb` 屏幕：Qt 显示音频进程中 Firefox 的整页截图，屏幕触摸经本机接口映射到 Selenium 网页点击，并非启动另一套独立浏览器。因此不用切到图形桌面，登录后 Cookie 仍保存在同一个专用 profile。登录界面按“关闭”会取消本轮网页操作；超时后可重新打开。QQ 网页的触摸缩放与扫码效果仍需在 Jetson 屏幕现场验收。

扫码界面若能看到网页但二维码较小，屏幕左侧应额外显示一张放大的清晰二维码；网页画面采用前后两帧交替加载，刷新时不应整屏闪白。手机扫码和左侧放大图的现场验收仍需人工完成。保留无桌面模式是当前默认；若以后需要网页键盘输入或任意浏览，需另设图形桌面登录模式，并处理正在使用的 Firefox profile 锁，不能同时以两个进程打开同一配置目录。
# 双设备网络入口（2026-10-25）

屏幕右上角“网络设置”：扫描、密码、DHCP/静态 IPv4、两台 IP、连接确认及超时回退。
安装系统辅助服务、配对、权限与测试说明见 [NETWORK_CONTROL.md](NETWORK_CONTROL.md)。
仅修改 Wi-Fi；保留大脑 10.0.0.50 / 小脑 10.0.0.51 的有线导航通信链路。

2026-10-30 Wi-Fi 修正：列表高度以footer实际y坐标计算，避免黄色提示覆盖列表；已保存只显示状态，选择SSID通过受本机请求头和Unix权限保护的saved_password接口读取该配置的PSK，仅返回到输入框，不放入周期状态/日志，响应no-store。连接/确认收起键盘，保留本次密码，离开页面清除。音乐切歌失败记录cause和有限错误原因，不再只记录QQMusicError类名；旧日志不足以区分空播放队列与网页等待超时。
