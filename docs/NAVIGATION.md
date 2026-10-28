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
- `robot_tools/navigation.py`：模型工具，不能设置运动确认、重启或任意服务名。
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

自动建图、resume可能启动运动，语音请求只提示到屏幕确认。屏幕选定后“确认执行”
才授权本次动作。restart仅维护区提供并需确认；以底盘已有有序stop/restart服务
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
自动建图、恢复探索请到屏幕确认。先按底盘手册进行无运动的启动→手动模式→暂停→关闭
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
