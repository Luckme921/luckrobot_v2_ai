# 大脑 ROS 2 底盘控制（2026-10-28）

契约以 BRAIN_START_AND_CONTROL_DEPLOYED_20261028.md 为最新部署状态，
模式/QoS/目标阶段见 BRAIN_ROS2_CONTROL_HANDOFF_20261028.md。
已撤掉本次未提交的 TCP 模式客户端及旧手册，不需要8765导航网关或TCP令牌。
注意本项目显示HTTP仍使用本机8765，这是另一个服务。

## 结构与启动

`bash scripts/run_robot.sh` 在安装有Humble时附带启动 `scripts/run_navigation.sh`。
桥接进程使用 `/usr/bin/python3`，source `/opt/ros/humble/setup.bash`，
Domain100、rmw_fastrtps_cpp、ROS_LOCALHOST_ONLY=0。保留现有有线地址
大脑10.0.0.50、小脑10.0.0.51，不配置路由、不改Wi-Fi、不照搬底盘环境脚本。
大脑不启动SLAM、AMCL、Nav2、电机节点，不订阅图像/点云，不发送cmd_vel。
`configs/navigation.yaml` 的 enabled 可关闭本地桥接。

职责：

- `edge/navigation/state.py`：双状态心跳、新鲜度和指令门控。
- `edge/navigation/ros_bridge.py`：rclpy异步服务和订阅、进程独占锁。
- `edge/navigation/manager.py`：单任务编排、启动等待、受理/完成/未知结果区分。
- `edge/navigation/bridge.py`：本地Unix socket和状态文件。远端业务链路始终是ROS。
- `robot_tools/navigation.py`：模型工具按明确语音任务直接执行；重启仅维护区，不能传任意服务名。
- `edge/display/qml/NavigationPanel.qml`：状态和确认操作；维护区折叠显示。

本地IPC是 `private/runtime/navigation/control.sock`（0600），状态快照
`status.json`；不提交private数据。云端与显示不直接导入rclpy，ROS Python ABI
和对话虚拟环境隔离。退出大脑桥接只停止订阅，不隐式关闭底盘或恢复任务。

## 功能与安全

工具 `navigation_control(command)` 支持status/start/stop/manual_mapping/
auto_mapping/finish_mapping/load_latest/pause/resume/cancel。
route_turn采用action=navigation_control、navigation_command=对应值。
与音乐/灯光可并发，但单批最多一个底盘操作，避免模式命令堆积。

开机只订阅监督和模式状态，不调用任何启动/运动服务。明确要求切模式时，如果软件栈
STOPPED，可请求start一次并等待RUNNING、manager_fresh及两次有效模式心跳后再发模式。
启动失败或超时不会继续。start只启动固定idle栈，不代表定位/导航就绪。

按用户最新要求，明确的语音任务可直接请求自动建图和resume，不要求再点屏幕。
语义含糊仍需询问，状态门控/单任务/超时不重发保留。触摸操作选定后确认，防止误触。
restart仅维护区提供并需确认；以底盘已有有序stop/restart服务
处理，不用SSH/systemctl/kill关闭运动进程，不传路径、PID、shell等参数。
维护区“已核对未知结果”只解除本地待核对标记，绝不重发旧指令。

服务success仅代表受理。任务显示starting/calling/accepted/running/completed/
rejected/failed/outcome_unknown等。接收服务响应之后的新鲜状态才用于确认完成。
服务调用8秒超时标记结果未知，无自动重试；未完成的任务不堆积普通模式请求，
暂停/取消/有序关闭可用于明确中断。系统实例变化废弃旧任务假设，不恢复旧运动。

`/robot/system/status` 和 `/mapping/status` 使用RELIABLE、TRANSIENT_LOCAL、depth1。
首条保留消息不足以认为在线；必须后续周期更新，间隔超过3秒或实例/会话变化重新确认。
两类心跳均按本地单调时钟计时；mapping.updated_unix不是心跳。map_ready与
navigation_ready不是主门控依据，目前使用完整mapping/status中的map和state。
RUNNING不等于NAV_READY，完整地图导航就绪需fresh、NAV_READY、map.complete=true。
未知状态、非法JSON、无地图、双服务提供者均保守拒绝新任务。

软件暂停不是物理急停。断网不保证停车；现有语音emergency_stop日志也不是电机急停。
自动运动验收必须有人看护、物理急停可用；本次自动测试和部署不启动探索或目标。

## 未启用范围

本阶段不实现Nav2目标队列、语义地点坐标或初始位姿发布；旧navigate_to返回unsupported，
不假装已经到达。没有自动全局重定位、服务端控制权租约；RViz与大脑须约定单写入者。
/mapping/update_map和save_checkpoint不暴露给第一阶段自动流程；如需保存未完成地图
按底盘手册人工验收，不把stop当保存。维护重启后需重新核对地图/定位。

## 测试操作

在项目根目录：

```bash
.venv/bin/python -m scripts.navigation status
.venv/bin/python -m scripts.navigation watch
tail -F logs/navigation-latency.log logs/audio-latency.log
```

CLI默认只读。语音可问“小脑现在什么状态”，或明确请求启动小脑软件。
自动建图和恢复探索可由明确语音任务直接请求，或在屏幕操作。先按底盘手册进行无运动的启动→手动模式→暂停→关闭
验收，再由现场操作者决定运动测试。不要把这些命令整段依次执行。
状态API：GET /navigation/status（本机8000）或 /api/navigation/status（显示8765）。
日志[NAVIGATION]包含本地task_id、命令和结果；Trigger不携带去重ID，本地ID不代表远端幂等。

## 音乐唤醒暂停

唤醒、纯唤醒本地回复、命令开始、处理中KWS与音乐工具完成后的取消检查都暂停音乐。
不再依赖主循环的旧music_playing值；QQ所有播放页均暂停并验证。暂停失败只显示错误，
不继续播报造成混音。播放、歌单推进和暂停共享锁，后台不覆盖暂停结果。
浏览器在途操作可能仍需等待驱动锁，因此不是零延迟。不会说完话自动恢复音乐。
验收：播放歌曲→喊Lucky→音乐暂停→回复不混音→说继续播放或点击按钮恢复。
日志看PAUSE_CONFIRMED、WAKE_PAUSED、WAKE_PAUSE_FAILED。

## 本次验收记录（2026-10-28）

- Windows：398项单测通过（1项平台相关跳过）；Jetson：398项通过。
- 大脑Humble/FastDDS/Domain100实际发现小脑监督节点；只读订阅302秒收到303次
  system/status，均为STOPPED；最大间隔1.00090秒，p95为1.00044秒，无超过3秒断流。
  此项仅验证监督心跳，未验证运行栈启动后的mapping话题。
- Jetson Qt offscreen加载5秒未出现QML解析错误；已部署并启动显示及机器人服务。
- 新ROS桥接进程唯一，屏幕API和CLI真实返回监督fresh=true、STOPPED、stack_alive=false。
  没有发送start/建图/恢复/目标等真实操作，不以通信成功代替运动安全验收。
- 初始化发现ROS setup脚本不兼容bash nounset，已在source期间临时关闭-u并恢复。
  修复后实际桥接启动正常；旧日志中的启动错误为此前记录。
- 用户暂不方便现场试听，音乐唤醒暂停/屏幕触摸仍待现场验收，已通过后台逻辑回归。

## 屏幕备用控制台与 RViz（2026-10-28 晚间更新）

Nav2入口缩小为左下角21像素低饱和红色文字。主区包含查询状态、启动/结束小脑软件、
手动/自动建图、暂停、恢复、取消。“地图与维护”保留完成手动建图、加载已有地图、
重启、核对未知结果。所有语音支持的指令均有触摸入口。
自动建图完成会自动保存并切定位，不用再点完成/加载；手动建图完成和启动后加载旧图
仍需这两个指令，因此移入次要区域而非删除。

左上角RViz入口使用本机原生OpenGL窗口；顶部提供重新打开/刷新及返回机器人。
刷新/关闭仅管理本进程拥有的RViz，不调用ROS模式服务，也不重启小脑。
实际配置已从小脑指定安装目录复制到大脑 `~/luckrobot_rviz/navigation.rviz`，不修改原件。
每次打开生成 `private/runtime/rviz-monitor.rviz` 副本，保留地图/路径等显示，移除目标、
初始位姿和Nav2控制面板，避免监视界面成为第二个运动指令来源。窗口按实际X11分辨率
布局，顶部预留70像素控制栏。模型mesh资源仍需大脑安装对应描述包才能解析。

RViz不能在linuxfb软件渲染界面中直接运行，因此显示服务切为最小X11+Openbox会话，
没有完整桌面面板，仍默认全屏机器人。依赖xinit/xauth/openbox/wmctrl/unclutter。
服务模板 `scripts/luckrobot-display-x11.service`；原framebuffer服务部署前保留备份。
新入口为 `scripts/run_display_session.sh`，X11禁止TCP监听、使用0600私有Xauthority。
大脑重启不自动打开RViz。显示诊断看journalctl -u luckrobot-display.service，
RViz诊断看logs/rviz.log。回退时恢复原显示service并daemon-reload/restart即可。

### 2026-10-28 RViz 实机部署记录
- 小脑原始配置复制到大脑 `~/luckrobot_rviz/navigation.rviz`；运行副本保留显示项，去掉目标/初始位姿工具和 Nav2 控制面板。
- 显示服务使用轻量 X11/Openbox，无完整桌面；HDMI 选用 1920×1080，失败则保留可用模式。需要 xinit、openbox、wmctrl、unclutter、ros-humble-nav2-rviz-plugins。
- Qt 5.15 顶部独立工具栏提供刷新和返回；窗口发现排除 RViz splash，只操作本程序拥有的主窗口。刷新不调用底盘服务。
- Windows 400 项测试通过（跳过 1）；Jetson 400 项测试通过。实机已验证 OpenGL、窗口适配、打开和刷新。
- 当前小脑监督状态在小脑本地为 STOPPED；大脑订阅仍 waiting_for_ros，RViz 缺少 map TF。地图/跨机状态链路尚未验收，不应宣称导航可用；未为测试启动底盘运动。
