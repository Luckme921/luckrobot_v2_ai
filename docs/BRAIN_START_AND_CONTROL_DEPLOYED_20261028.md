# 大脑控制小脑：已部署启动与交互说明

日期2026-10-28。此文件是当前启动接口的部署补充，优先于旧文档中“监督接口未实现”的描述。详细模式接口见BRAIN_ROS2_CONTROL_HANDOFF_20261028.md。

## 已部署

小脑10.0.0.51，ROS2 Humble，Domain100，FastDDS。用户systemd服务luckrobot-supervisor.service已enable并运行，nvidia的Linger=yes，开机无需SSH登录即可启动监督服务。尚未通过真实整机重启验收，不把enable等同于重启实测。

开机只启动轻量监督服务，不自动启动导航或探索。Jetson必须已上电。运行栈由大脑请求启动，固定idle模式，不恢复旧运动任务。

## 大脑启动环境

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=100
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
```

大脑有线地址建议未占用的10.0.0.52/24。先验证有线DDS通信，不需要启动TCP8765。不要照搬底盘本机XML文件路径。

## 精确系统接口

三个服务均std_srvs/srv/Trigger，请求{}：

```bash
ros2 service call /robot/system/start std_srvs/srv/Trigger '{}'
ros2 service call /robot/system/stop std_srvs/srv/Trigger '{}'
ros2 service call /robot/system/restart std_srvs/srv/Trigger '{}'
```

这些是操作参考，不是按顺序一次执行的脚本。

- start：启动唯一managed_mapping.launch.py，boot_mode=idle，auto_explore=false。已经运行时返回already started，不重复启动。检测到外部机器人节点时拒绝接管。
- stop：调用mapping/pause，等待管理器PAUSED（管理器已确认里程计静止），然后向所属launch进程组发送SIGINT，等待退出。监督服务保持在线。暂停失败、静止未确认或退出超时会FAULT，不强制杀进程、不伪报关闭成功。
- restart：按stop流程结束旧栈，然后重新启动到RUNNING/IDLE。关闭失败不启动新栈。已停止时等价于start。重启不等于继续任务，不恢复旧目标；大脑必须重新选择模式并处理定位。

模式服务busy时不堆积多个命令。系统操作超时先查询状态，不连续重试。Trigger没有业务请求ID去重；start仅通过已存在子进程实现重复启动保护。

## 读取系统状态

```bash
ros2 topic echo /robot/system/status std_msgs/msg/String --qos-reliability reliable --qos-durability transient_local
```

String内JSON，约1Hz。QoS reliable/transient_local/depth1：

```json
{"schema":1,"state":"RUNNING","reason":"manager_idle_ready","instance_id":"唯一运行实例","stack_alive":true,"manager_fresh":true,"manager_state":"IDLE","updated_unix":1793170975.0}
```

state：STOPPED、STARTING、RUNNING、STOPPING、FAULT。
RUNNING表示机器人栈已启动，不代表导航定位就绪。还需订阅/mapping/status并等待NAV_READY。manager_fresh=false不能放行新的导航任务。stack_alive只是launch进程状态，不是所有传感器健康证明。

系统status.updated_unix每次发布更新；mapping/status.updated_unix仍是状态转换时间，二者不要混淆。两类状态都用大脑本地单调时钟监测接收间隔，超过3秒标记过期。刚订阅至少等后续周期消息，不仅依赖保留消息。

## 任务编排

1. 等监督状态在线。
2. STOPPED时请求start，等待RUNNING且manager_fresh=true。
3. 调用/mapping/auto_mapping或/manual_mapping或/load_latest。
4. 自动建图完成会自动保存并切定位，不额外调用load_latest。
5. NAV_READY才进入导航目标阶段。重启后可能WAITING_INITIAL_POSE，不能自动假设旧位置。
6. 结束当前任务用/mapping/cancel；暂时暂停用/mapping/pause。
7. 关闭整个机器人软件栈用/robot/system/stop。
8. 明确需要重启软件栈用/robot/system/restart。实例ID变化后清除大脑旧goal handle与待执行运动授权，重新核对地图和定位。

ROS模式服务和Nav2 Action的详情见主交接文档。大脑与RViz只能一个发目标。第一阶段不发/cmd_vel。

## 关于launch、节点和线程的关闭

大脑不能传任意launch路径、PID、线程名或shell命令。现有接口管理完整机器人栈；探索暂停、取消通过模式管理器执行。单独重启某个传感器/定位节点尚未开放，因为其依赖和TF状态需要联动恢复。如以后确需局部恢复，应新增固定白名单组件及依赖恢复测试。

系统stop/restart会取消运动任务，不能视为“保存并正常结束建图”；需要保留未完成地图时先在支持状态调用/mapping/save_checkpoint并确认结果，再关闭。需要完整地图时由用户确认finish_mapping，或等待自动探索完成。

## 故障边界

本接口不是急停。若管理器不响应、无法证明静止，stop/restart会报告FAULT，需现场急停或维护处理，不能承诺任何故障下都能远程安全停下。

systemd监督进程崩溃后会重启，但不会主动重发旧任务。KillMode=control-group在停止服务时会影响其子进程，所以正常业务必须用ROS stop/restart，不直接systemctl restart监督服务。网络断线不自动取消自主任务。

## 维护（底盘本机，非大脑日常业务）

```bash
systemctl --user status luckrobot-supervisor.service --no-pager
journalctl --user -u luckrobot-supervisor.service -n 80 --no-pager
loginctl show-user nvidia -p Linger
```

运行栈日志：~/.local/state/luckrobot/stack_<instance_id>.log。
监督源码：~/ros2_ws/tools/robot_system_supervisor.py。
服务文件：~/.config/systemd/user/luckrobot-supervisor.service。

维护禁用前先通过ROS stop确认STOPPED，再执行systemctl --user disable --now luckrobot-supervisor.service。

## 验收记录

已在小脑通过ROS真实调用验证：start到RUNNING/IDLE、重复start返回already started、stop到STOPPED。未发送运动目标。restart已验证旧栈退出、新instance_id启动并到RUNNING/IDLE。另一台大脑网络联调与断电重启后的自启验证仍需执行。
