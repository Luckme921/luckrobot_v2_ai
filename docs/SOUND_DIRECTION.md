# 声源方向接口

Windows 本地补齐版，2026-09-20。设备端 6b7e197 之前已实现并通过 205 项测试，但设备关闭前未拉回该提交。本地按相同接口补齐，额外校验轮询间隔并容忍关闭资源异常；并非已取得设备提交。设备开机后先 fetch 再合并，保留两端历史。

edge/audio/direction.py 提供 XvfDirectionReader.read() 与 DirectionMonitor.latest(max_age_seconds=2)。仅读取 XVF3800（2886:001a）DOA_VALUE：resource 20、读命令 0x92、5 字节（状态+两个小端 uint16：角度/VAD），USB 超时 500ms，不重设 USB、不解绑音频驱动、不修改固件。参考：https://wiki.seeedstudio.com/respeaker_xvf3800_python_sdk/ 。

默认独立线程每秒 print 一条 [DOA] JSON，与对话并行。错误每 5 秒重试并清除旧快照；退出时停止线程。sensor_azimuth_deg 为麦克风 0–359°方向，speech_active 为硬件 VAD；direction_valid 不等于准确度或人声身份置信度。机器人扬声器可能影响读数。安静时角度可能残留，必须看有效标志。

distance_m、position_xyz_m 始终 null，没有距离/三维定位功能。front_offset_deg 默认 null，不标注机器人左右；现场正前方讲话所得角度用于偏移标定，再向右移动验证 clockwise。校准后 robot_bearing_deg 约定前0、右90、后180、左270度。未接入运动控制，未来跟随还需视觉/测距/避障。

## Jetson 使用

依赖 pyusb==1.3.1 和系统 libusb。USB 权限规则 configs/99-luckrobot-xvf3800.rules 只授权此设备给 plugdev 组。设备此前已安装依赖和规则，无需运行 root 音频进程。迁移设备时将规则安装到 /etc/udev/rules.d 并重载、重新插入设备，确保运行用户属于 plugdev。

    .venv/bin/python -m edge.audio.direction --samples 10 --interval 1
    tail -f logs/audio-latency.log | grep --line-buffered '\[DOA\]'

configs/audio.yaml: audio.sound_direction.enabled 开关、interval_seconds 轮询间隔、front_offset_deg 与 clockwise 标定参数。run_robot.sh 启动后输出到 audio-latency.log。

此前设备只读实测为353°、VAD=false，未做四个方向的准确度验收。本轮设备关闭，仅验证本地逻辑，不连接设备。
