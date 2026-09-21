# reSpeaker 声源方向接口

2026-09-20，设备 USB 2886:001a，XVF3800 四麦阵列。实现 edge/audio/direction.py 的 XvfDirectionReader.read()，以及 DirectionMonitor.latest(max_age_seconds=2)。仅 USB vendor IN 读取；不设置 USB configuration，不解绑音频驱动，不修改固件、增益或 LED，不发送机器人动作。

## 数据

日志前缀 [DOA]，默认每秒一次：sensor_azimuth_deg 是麦克风坐标的 0–359 度方位角；speech_active 是硬件 VAD；direction_valid 仅表示语音活动且报文有效，不是方向准确度或说话人身份置信度。安静时可能残留旧角度，必须看 direction_valid=false。播放机器人声音/音乐时读数可能受影响；不代表人类目标。

设备只返回方位角和 VAD，本接口没有距离、XYZ 位置、高度或可追踪目标 ID，因此 distance_m、position_xyz_m 始终 null。软件接收时间 timestamp/monotonic 不是声音发生时刻。latest 拒绝超过指定时间的数据，读取失败清除旧数据。

## 坐标标定

当前 front_offset_deg=null，未假定麦克风朝向；robot_bearing_deg=null。让人站在机器人正前方讲话，记录稳定角度作为 front_offset_deg，再从前方移动到右侧确认 clockwise。转换后约定机器人正前 0°、右 90°、后 180°、左 270°；安装和正反转未经现场标定前不可作运动依据。单阵列方位不能直接求目标位置或跟随距离，后续运动需结合视觉/测距/避障及高层动作接口。

## Jetson 使用

依赖 pyusb==1.3.1 和系统 libusb。USB 权限规则 configs/99-luckrobot-xvf3800.rules 只授权此设备给 plugdev 组。设备此前已安装依赖和规则，无需运行 root 音频进程。迁移设备时将规则安装到 /etc/udev/rules.d 并重载、重新插入设备，确保运行用户属于 plugdev。

## 启动和检查

configs/audio.yaml 的 audio.sound_direction.enabled=true 后，run_robot.sh 的音频进程启动独立后台读取线程，输出到 logs/audio-latency.log。单次 USB 超时 500ms，失败每 5 秒重试；热插拔重连不阻塞音频主循环。退出时停止线程并释放 USB 资源。



    .venv/bin/python -m edge.audio.direction --samples 10 --interval 1
    tail -f logs/audio-latency.log | grep --line-buffered '\[DOA\]'


依赖 pyusb==1.3.1 与系统 libusb。当前已为 jetson 安装依赖，并把 configs/99-luckrobot-xvf3800.rules 安装到 /etc/udev/rules.d/；该规则只给 plugdev 组授予此 VID/PID 的 USB 访问权限，当前用户已属于该组。规则重载后新插入生效，当前设备节点已调整组权限，无需以 root 运行机器人。

协议：DOA_VALUE resource=20，command=18（读取位 0x80），返回状态字节+两个小端 uint16（角度、VAD）。拒绝非零状态、错误长度和非法字段，避免把 255°以上角度截断。

设备实测成功读取 353°、VAD=false；这是静态读数，不是现场方向准确度验收。请在阵列不同方向讲话确认变化，再完成前方标定。



2026-09-21：默认 log_samples=false，仅关闭后台采样打印，不停止读取/latest 接口。相同错误去重；独立命令行工具仍打印数据。
