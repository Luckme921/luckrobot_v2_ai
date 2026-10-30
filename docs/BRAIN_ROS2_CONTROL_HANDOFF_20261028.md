# 大脑 Jetson → 底盘 Jetson：ROS 2 控制开发交接

日期：2026-10-28

**部署更新：启动/停止/重启监督接口现已实现。请先阅读同目录 `BRAIN_START_AND_CONTROL_DEPLOYED_20261028.md`；本文第0节关于“监督接口尚未实现”的文字为设计历史，以该部署补充为准。**
决策：**ROS 2 为大脑的主控制接口；TCP网关只作为备用兼容接口。** 本文件取代旧TCP文档在“大脑主接口选型”上的建议。底盘现有服务无需因为改用ROS而重写，但双机通信及业务联调仍需完成。

请另一台Jetson上的AI按照本文开发。先检查环境、完成只读通信，未经现场操作者明确允许，不启动探索或发送运动目标。


## 0. 最新需求：大脑是统一任务调度者（优先于后文第一阶段边界）

用户明确要求：大脑决定小脑启动、分配任务、读取状态，后续统一集成导航目标。最终不是由主人每次SSH启动导航。以下是目标架构，新增监督服务尚未实现，不得把设计接口写成现有接口。

### 0.1 三层职责

1. 大脑任务管理器：决定是否启用小脑、选择模式、编排任务、发送目标、处理结果、决定暂停/取消/下一任务。
2. 小脑轻量监督服务：小脑开机后由systemd启动，保持ROS通信，接收启动/停止请求，管理唯一机器人launch，报告进程与启动结果。没有业务指令时不自动开始探索或导航。
3. 小脑机器人运行栈：由监督服务启动，包括现有模式管理器、传感器、定位、规划、控制。大脑决定任务，小脑保留避障、速度限制和故障停车责任，不能因大脑要求而绕过。

通信链：大脑 → 常驻监督服务 → 现有模式管理器 → 探索/Nav2 → 控制与电机。

“启动”指Jetson已上电、Linux正常运行后启动机器人软件。软件不能保证唤醒断电的Jetson；硬件远程上电不在当前接口范围。

### 0.2 当前与目标的差距

当前managed_mapping.launch.py boot_mode:=idle可以等待模式指令，但仍需有人启动该launch，且它会启动机器人基础栈；不是只运行轻量通信服务。现有/mapping/*服务只在该管理器运行时存在，无法启动尚未运行的管理器。

因此不能告诉大脑“调用auto_mapping就能从完全未启动的软件状态自动启动一切”。必须先补小脑监督服务及systemd部署。大脑端AI可以先实现客户端状态机和模拟测试；真实启动接口需与小脑端开发协调，不能靠运行任意SSH shell作为正式业务协议。

### 0.3 拟新增监督接口（设计提案，未部署）

| 接口 | 建议类型 | 行为 |
|---|---|---|
| /robot/system/start | std_srvs/srv/Trigger | 请求启动唯一managed launch，参数固定为idle；重复调用不得再起一套 |
| /robot/system/stop | std_srvs/srv/Trigger | 请求有序暂停、确认静止后停止机器人栈；保留监督服务在线 |
| /robot/system/status | std_msgs/msg/String | 周期JSON：监督状态、启动实例ID、错误、运行栈可用性 |

服务受理与执行成功分离；状态建议STOPPED/STARTING/RUNNING/STOPPING/FAULT，消息schema单独定义。RUNNING只代表运行栈及管理器可用，不代表NAV_READY。接口名称须双方最终确认后才启用。

start应幂等、串行、带进程互斥与启动超时；已运行时返回已有状态，不重建地图。stop不能直接kill运动进程了事，应走现有暂停和静止确认；失败报告FAULT，不能伪报已停。进程崩溃不得盲目自动恢复旧运动任务。监督服务不接受任意命令行、路径或shell脚本。

监督服务失联与机器人状态过期均向大脑报告。重连只核对状态，不默认重发启动/探索/目标。systemd可以重启监督进程，但监督恢复后必须核对已有子进程，不能产生第二套栈或自动继续旧目标。底盘失效停车仍需独立控制层保障，不依赖大脑通信。

### 0.4 大脑实际调度流程

```text
大脑收到用户任务
  → 查询监督服务在线及机器人栈状态
  → 必要时请求start，等待RUNNING及新鲜/mapping/status
  → 按任务调用manual_mapping / auto_mapping / load_latest
  → 观察状态，处理受阻、等待初始位姿、失败
  → 导航任务等待NAV_READY
  → 发送一个Nav2目标，持续接收反馈和终态
  → 成功后推进下一个任务；失败交由明确恢复策略
  → 按用户/业务规则保持待命，或请求有序stop
```

自动建图成功后已经自动进入定位，不追加load_latest。启动机器人栈与切模式是两层操作；软件启动成功不代表定位完成。

### 0.5 任务、目标与控制权

大脑维护自己的task_id、task_type、map_id、目标列表、当前goal_id和任务状态。初期不新增虚构字段到已有Trigger/Nav2消息；这些字段属于大脑任务数据库或内存状态。

日常运行由大脑唯一发模式和导航目标；RViz只观察。需要人工RViz接管时，大脑先取消自己的目标、等待终态并进入MANUAL_OVERRIDE，不再继续队列；人工结束后显式归还控制。现有底盘没有强制租约仲裁，正式产品需新增服务端目标控制权机制，初期依靠明确单写入者约定。

大脑不得在EXPLORING期间发送导航目标抢占探索。目标队列按成功结果推进，不能因收到accepted或机器人停止就判成功。暂停后旧目标已可能取消，恢复任务时由大脑明确决定重新提交，并核对地图版本和定位。

### 0.6 实施顺序与交付责任

A. 大脑端：完成ROS发现、只读状态订阅、服务客户端、任务状态机和模拟监督接口测试。
B. 小脑端：实现监督服务、systemd常驻、启动互斥、有序停止、状态与启动失败反馈。未经验证不启用自动运动恢复。
C. 双端：验证“仅小脑监督服务运行 → 大脑启动运行栈 → 手动模式 → 暂停 → 有序停止”，先不自动探索。
D. 双端：验证大脑发起自动探索至NAV_READY，再验证Nav2短目标及队列。
E. 后续：补重启后的可信初始定位、控制权仲裁、故障恢复和持久任务一致性。

最终验收：用户无需每次SSH开launch；大脑能启动小脑软件、分配任务、读状态、判成功/失败、取消和有序停止。硬件未上电、网络不通或缺少可信位姿时应明确报告原因，不能宣称能无条件完成任务。

## 1. 系统分工

**大脑负责**用户意图、模式选择、任务编排、状态展示、以后导航目标队列。

**底盘（小脑）负责**传感器、EKF、SLAM/定位、地图版本、探索、规划、控制、避障与电机输出。

当前定位是 **SLAM Toolbox localization，不是AMCL**。编码器＋IMU融合EKF提供odom→base_footprint，SLAM Toolbox提供map→odom。不要在大脑启动AMCL或另一套SLAM发布同名TF，不要在两台设备分别启动同名Nav2服务。

当前实机已观察到自动探索完成→保存校验→加载定位→NAV_READY。这不代表大脑ROS联调、任意场景探索或动态障碍处理已全部验收。

## 2. 接口选型和控制权

采用：

- ROS Service：模式请求。
- ROS Topic：模式、保存结果、导航就绪状态。
- ROS Action：第二阶段提交导航目标，获取反馈/结果和取消。

TCP不是主路径，不要求大脑连接8765或配置TCP令牌。保留旧代码即可。**同一时刻只允许一个业务写入者**：大脑控制或人工RViz控制，不能两套程序同时发模式/目标。

当前底盘没有控制权租约或跨客户端仲裁；第一版大脑必须通过自身工作模式和操作者约定避免冲突。不要声称已有服务端锁阻止RViz抢目标。

## 3. 双机环境和网络

底盘：ROS 2 Humble，ROS_DOMAIN_ID=100，RMW_IMPLEMENTATION=rmw_fastrtps_cpp。
底盘有线：10.0.0.51/24。大脑可使用未占用的10.0.0.52/24。

同一个Domain ID不等于必然互通，也不是鉴权。必须验证DDS发现、服务调用、QoS、网卡和时间同步。优先两端都用Humble及Fast DDS；不要盲目卸载已有ROS，先检查版本。

大脑检查：

```bash
ip -br address
ip route
ip route get 10.0.0.51
ping -c 4 10.0.0.51
ls /opt/ros
printenv ROS_DISTRO ROS_DOMAIN_ID RMW_IMPLEMENTATION ROS_LOCALHOST_ONLY
printenv FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE ROS_DISCOVERY_SERVER
```

有线直连不配置默认网关/DNS，保留Wi-Fi上网路由。网卡名必须通过实际系统识别，不假设eth0。不得未经确认修改正在承载SSH的网卡。

大脑终端基本环境（确认已安装Humble与rmw_fastrtps_cpp）：

```bash
source /opt/ros/humble/setup.bash
# 如果已有大脑工作空间，在这里source它自己的install/setup.bash。
export ROS_DOMAIN_ID=100
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
```

底盘继续使用：

```bash
source ~/ros2_ws/tools/robot_env.sh
```

**不要将底盘robot_env.sh中的绝对路径原样用于大脑。** 底盘使用自己的fastdds_udp.xml，大脑应检查本机DDS配置是否把通信限制到回环或其他接口。需要调整时先保留原配置，并检查有线双向连通；同Domain不要求两端照搬同一XML。

DDS不是TCP8765。开放8765不会解决ROS发现问题。检查防火墙和组播/单播通信，不要直接关闭全部防火墙。若需要静态发现或Discovery Server，应作为明确的双端配置变更实施并验证，不能只改一端。

第一阶段只订阅小型管理状态，不订阅深度图、RGB原图、点云，也不要启动全量rosbag。过去底盘遇到过DDS UDP丢包，大脑接入不得挤占感知通信。

两机时间应通过NTP/chrony等保持一致；只读查看`timedatectl status`，如已有chrony可查看`chronyc tracking`。服务Trigger无时间戳，但未来导航和初始位姿会使用时间戳，不能忽略时间同步。不要在机器人运动时突然大幅校时。

## 4. 现有模式服务：精确契约

以下全部类型为 **std_srvs/srv/Trigger**，请求为空`{}`，响应包含success和message。

| 服务 | 用途 | 语义/约束 |
|---|---|---|
| /mapping/manual_mapping | 手动建图 | 由RViz或受控客户端发目标，不启动自动探索 |
| /mapping/auto_mapping | 自动探索建图 | 会自主移动，完成后自动保存并切定位 |
| /mapping/finish_mapping | 明确结束手动建图 | 是用户确认地图可完成，不是算法覆盖证明 |
| /mapping/load_latest | 加载最新完整地图定位 | 对应旧TCP navigation，可能等待初始位姿 |
| /mapping/pause | 暂停 | 等到PAUSED才算完成，不是硬件急停 |
| /mapping/resume | 恢复 | mapping模式恢复自动探索；不是恢复旧手动目标 |
| /mapping/cancel | 取消 | 建图时可能保存不完整检查点 |
| /mapping/save_checkpoint | 保存不完整检查点 | 保存后PAUSED，不替代完整地图 |
| /mapping/update_map | 基于已定位的旧位姿图继续建图探索 | 仅NAV_READY且有map记录；已有代码，但独立验收未完成，第一阶段禁用此按钮 |

注意：**没有 /mapping/navigation 或 /mapping/status 服务。** 导航模式用load_latest，status是话题。

success=true只表示请求进入管理器，不等于执行完成。常见message：

- accepted; final result on /mapping/status
- busy; inspect /mapping/status
- command not valid in state ...

管理器串行执行工作，不是允许任意任务堆积的业务队列。普通请求遇到busy会被拒绝；pause/cancel可请求中断，但仍受停止流程和通信延迟影响。

与TCP区别：**直接ROS服务没有TCP网关的请求ID和去重缓存**。服务超时后结果未知，不得无脑重新调用。先观察状态，再决定是否重试；客户端生成自己的日志request_id，但不要以为它被Trigger服务用于幂等控制。

## 5. 状态话题与QoS

| 话题 | 类型 | 用途 |
|---|---|---|
| /mapping/status | std_msgs/msg/String | JSON完整会话状态，约1Hz发布 |
| /mapping/navigation_ready | std_msgs/msg/Bool | 当前是否NAV_READY，约1Hz发布 |
| /mapping/map_ready | std_msgs/msg/String | JSON地图版本记录；保存或加载时发布，不是周期心跳 |

三者发布QoS：KEEP_LAST depth=1、RELIABLE、TRANSIENT_LOCAL。订阅使用匹配QoS，可收到保留的最后状态。

ROS `/mapping/status`示例（值仅示意）：

```json
{
  "schema": 1,
  "session_id": "SESSION_ID",
  "state": "NAV_READY",
  "reason": "localization_health_stable",
  "mode": "localization",
  "retries": 0,
  "map": {
    "map_id": "MAP_ID",
    "prefix": "/home/nvidia/ros2_ws/map_store/versions/MAP_ID/map",
    "complete": true
  },
  "updated_unix": 1793158142.0
}
```

**直接ROS消息没有stale字段！** stale是旧TCP网关额外生成的。ROS大脑必须根据本地`time.monotonic()`记录回调接收时间，超过3秒未收到新状态就标为失联/状态过期。

updated_unix是状态转换时间，不是每次心跳时间；NAV_READY不变时它可能很旧，不用它单独判断失联。

TRANSIENT_LOCAL首条可能是保留消息。大脑新连接时至少看到后续一次周期更新，再认定通信在线；保留的map_ready不代表刚刚又保存了一次。

就绪判断：有效周期状态接收、最近3秒内收到状态、state==NAV_READY。对已有地图导航还检查map存在且complete=true。不能仅凭曾收到的navigation_ready=true长期放行。跨话题到达顺序没有原子保证，以完整status作为主要业务依据。

允许附加JSON字段；未知state显示原值并保守等待，不崩溃、不自动运动。

## 6. 状态含义

| 状态 | 大脑处理 |
|---|---|
| STARTING | 等待管理器初始化 |
| IDLE | 可选择模式 |
| MAPPING | 建图；manual_mapping_ready原因才表示手动模式就绪 |
| EXPLORING | 自动探索中 |
| BLOCKED | 受阻等待重试，不当完成 |
| EXPLORATION_COMPLETE | 可达范围探索完成，等待保存 |
| STOPPING | 停止旧任务并确认静止 |
| SAVING | 保存中 |
| CHECKPOINT_SAVED | 不完整检查点已保存，不当完整成功 |
| MAP_READY | 完整地图已保存校验，等待定位 |
| LOCALIZING | 加载/恢复定位中 |
| NAV_READY | 新鲜状态下表示导航就绪 |
| WAITING_INITIAL_POSE | 需要可信当前位姿 |
| PAUSED | 已暂停，等待明确操作 |
| INCOMPLETE | 覆盖仍未完成，保留检查点 |
| CANCELLED | 已取消，不自动恢复 |
| ERROR | 显示reason并保留诊断，不循环重发模式 |

完成不要求全部灰色未知消失，允许不可达狭窄/小残余未知。大脑不能用RViz截图或“机器人不动”自行宣布完成。

## 7. 推荐业务调用顺序

### 自动探索

1. 状态在线、允许切换时调用auto_mapping一次。
2. success=true后等待EXPLORING；中间可能有初始化等待。
3. 后续由底盘完成探索→静止→保存→校验→定位。
4. 最终NAV_READY且map.complete=true才向上层报告“地图已保存，导航就绪”。
5. 不追加finish_mapping或load_latest，不重复启动建图。
6. BLOCKED由管理器自行重试；耗尽后可能INCOMPLETE，不能自动finish_mapping掩盖失败。

### 手动建图

manual_mapping → 等待MAPPING且reason含manual_mapping_ready → 主人发RViz目标 → 用户明确确认结束 → finish_mapping → 等待NAV_READY。

暂停后继续手动建图用manual_mapping，不用resume。已有mapping会话切换manual/auto会保留；从其他模式进入建图可能开始新会话。

### 重启后导航

load_latest → 有可信种子位姿才加载定位，否则WAITING_INITIAL_POSE。

不能沿用搬动前的位置。当前自动全局重定位、等待时旧地图预览尚未补齐。这个限制是底盘定位功能限制，不会因改用ROS自动消失。

### 暂停和恢复

pause → 等待PAUSED。mapping模式resume会启动/继续自动探索；localization模式resume进行健康检查并恢复导航，不保证恢复已取消的手动目标。cancel后等待CANCELLED。

### 状态门控

manual_mapping、auto_mapping、load_latest通常从IDLE/MAPPING/PAUSED/NAV_READY/INCOMPLETE/CANCELLED/WAITING_INITIAL_POSE接受，仍需服务端busy检查。EXPLORING中切换模式先pause并等待。finish_mapping仅mode=mapping且MAPPING/PAUSED/INCOMPLETE允许。

已是NAV_READY不要重复load_latest，该实现可能重新要求初始位姿。一次只推进一个业务操作，不能把一串服务调用当成自动队列。

## 8. 无运动的双机联调命令

底盘管理器已运行就不要重启。若未运行，由现场操作者在底盘执行：

```bash
source ~/ros2_ws/tools/robot_env.sh
ros2 launch my_robot_mapping managed_mapping.launch.py \
  boot_mode:=idle auto_explore:=false
```

不要与旧机器人launch重复运行；不要在大脑启动这条launch。ROS主接口不需要启动TCP网关。

大脑完成环境设置后：

```bash
ros2 node list --no-daemon --spin-time 3
ros2 service list -t
ros2 topic info /mapping/status -v
ros2 topic echo /mapping/status std_msgs/msg/String \
  --qos-reliability reliable --qos-durability transient_local
```

应能看到/mapping相关服务、约1Hz状态。多份同名管理器/服务实例属于异常，先排查，不能任选一个调用。

若CLI daemon继承了旧环境，在确认不会影响业务后可执行`ros2 daemon stop`再重新查询；不要因此重启整个机器人。

先连续订阅5分钟记录接收间隔、最长间断，不能只用node list可见就宣布通信稳定。

## 9. 有人看护时的模式命令

这些命令在大脑端运行，前提是通信已验证且操作者明确允许。auto_mapping会移动机器人。

```bash
ros2 service call /mapping/manual_mapping std_srvs/srv/Trigger '{}'
```

```bash
ros2 service call /mapping/auto_mapping std_srvs/srv/Trigger '{}'
```

```bash
ros2 service call /mapping/pause std_srvs/srv/Trigger '{}'
```

```bash
ros2 service call /mapping/resume std_srvs/srv/Trigger '{}'
```

```bash
ros2 service call /mapping/cancel std_srvs/srv/Trigger '{}'
```

```bash
ros2 service call /mapping/finish_mapping std_srvs/srv/Trigger '{}'
```

```bash
ros2 service call /mapping/load_latest std_srvs/srv/Trigger '{}'
```

上面是命令参考，**不是依次全部执行的脚本**。save_checkpoint和update_map第一阶段不放到自动流程中。

## 10. 大脑rclpy实现要求与只读示例

建议ament_python包名`luckrobot_brain_bridge`，依赖rclpy/std_msgs/std_srvs；第二阶段才增加nav2_msgs/action_msgs/geometry_msgs。现有大脑项目有组织方式则优先复用。

职责划分：状态订阅、服务客户端、业务状态机、CLI/UI适配、日志、测试。禁止在subscription回调里同步阻塞等待服务；使用call_async并让executor持续spin。

只读状态订阅示例，可直接保存为`watch_robot_state.py`：

```python
import json
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from std_msgs.msg import String

class Watch(Node):
    def __init__(self):
        super().__init__('brain_robot_state_watch')
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.last_rx = None
        self.session = None
        self.updates = 0
        self.status = {}
        self.create_subscription(String, '/mapping/status', self.receive, qos)
        self.create_timer(1.0, self.report)

    def receive(self, msg):
        try:
            data = json.loads(msg.data)
            if not isinstance(data, dict) or not isinstance(data.get('state'), str):
                return
        except (ValueError, TypeError):
            return
        now = time.monotonic()
        # Require a later periodic sample after reconnect/gap/session change.
        if (self.last_rx is None or now-self.last_rx > 3.0 or
                data.get('session_id') != self.session):
            self.updates = 0
        self.session = data.get('session_id')
        self.updates += 1
        self.last_rx = now
        self.status = data

    def report(self):
        fresh = (self.last_rx is not None and self.updates >= 2 and
                 time.monotonic()-self.last_rx <= 3.0)
        ready = fresh and self.status.get('state') == 'NAV_READY'
        self.get_logger().info(
            f'fresh={fresh} ready={ready} state={self.status.get("state")} '
            f'reason={self.status.get("reason")}')

rclpy.init()
node = Watch()
try:
    rclpy.spin(node)
except KeyboardInterrupt:
    pass
finally:
    node.destroy_node()
    rclpy.shutdown()
```

这是只读示例，不是完整业务客户端。生产代码还要做session变化处理、忙状态、异步服务超时和未知结果处理。调用超时不能当作“没有执行”。模式命令不自动重试；确认状态后才允许用户重试。

本地记录command/request_id、服务响应、state/reason、session_id/map_id和本地单调时间。不要将未经验证的旧状态用于恢复动作。

## 11. 第二阶段：导航Action，而不是速度命令

模式接口联调通过后，可使用现有Nav2 Action：

- 名称：`/navigate_to_pose`
- 类型：`nav2_msgs/action/NavigateToPose`
- 目标：`pose.header.frame_id = 'map'`，当前ROS时间，x/y单位米，朝向四元数归一化。
- `behavior_tree`默认留空，沿用底盘当前默认行为树，不给不存在的本地路径。
- 反馈：当前位姿、剩余距离、导航时间、恢复次数等，按本机Humble消息定义读取。
- 结果：以Action终态SUCCEEDED/ABORTED/CANCELED为准，不能仅凭目标受理。

大脑需安装匹配的nav2_msgs接口。先只读验证：

```bash
ros2 action list -t
ros2 action info /navigate_to_pose
ros2 interface show nav2_msgs/action/NavigateToPose
```

**初期Action发目标仅允许NAV_READY且状态新鲜，并关闭自动探索、确认人工RViz不再发目标。** 若今后支持手动建图中的大脑目标，应单独设计MAPPING/manual状态授权。

大脑维护任务队列：一个目标成功后再发下一个；失败要上报/决定重规划，不默默跳过。新目标可能抢占旧目标，不能依赖Nav2帮忙保存大脑的整串任务。取消使用本客户端持有goal handle的cancel_goal_async，不无差别取消他人任务。

current map_id必须与任务绑定，换地图后废弃旧坐标任务。Nav2 Action本身没有我们的map_id字段，大脑必须在发送前自己校验，不要虚构字段加入ROS消息。

当前无服务端全局目标仲裁，因此第一版只能靠单写入者约定；正式多客户端使用前需补底盘目标网关/控制权机制。网络断线不保证任务取消，不承诺断线停车；急停独立。

## 12. 初始位姿接口及限制

已有ROS话题：`/mapping/initial_pose`或`/initialpose`，类型`geometry_msgs/msg/PoseWithCovarianceStamped`。

管理器只在WAITING_INITIAL_POSE且空闲时接受；frame_id必须map；时间戳需要新鲜（当前校验约-0.2至2秒）；四元数归一化，x/y/yaw有效。

不要发送(0,0,0)“试一下”，不要复用旧地图的坐标，也不能靠重发绕过定位。只能来自可信当前位姿，例如已知停靠点或正确旧地图上的人工标定。旧地图预览、自动全局重定位尚未补齐，因此第一阶段大脑只提示待处理，不自动发初始位姿。最终必须等NAV_READY。

## 13. 地图与部署约束

地图路径在底盘：`/home/nvidia/ros2_ws/map_store`，current.json指向最新完整版本。保存文件包含栅格地图和SLAM位姿图。不完整检查点不替换完整版本。

底盘的/mapping/map_ready记录是元数据，不是把地图文件传到了大脑。大脑不要访问自己机器上的同名路径并以为能读到底盘地图。

当前ROS模式服务没有鉴权；可信直连网段与单写入者约定是当前前提。需要访问控制时后续评估SROS2或专门网关，不把Domain ID当密码。

开机自启未完成；先人工启动管理器联调。大脑自己的服务如配置开机启动，只自动订阅状态，不自动发运动命令。不要在本次接口开发顺便修改底盘运动参数、DDS缓冲、规划器或安全层。

动态障碍残留修复仍需实机验证；当前选用ROS不改变底盘避障算法。不要将网络接口成功作为避障问题解决的证据。

## 14. 测试和交付标准

第一阶段：

- 双机同域能持续收到状态，至少5分钟无未解释的长断流。
- transient-local首条和后续心跳能区分；断开网络超过3秒显示状态过期。
- session变化、未知状态、非法JSON、map=null均正常处理。
- 单服务异步调用、busy拒绝、超时结果未知都不会引发命令风暴。
- 大脑重启只订阅，不自动建图/恢复。
- 有人看护验证manual_mapping、pause，再验证auto_mapping到NAV_READY。
- 不重复load_latest，不自动finish_mapping掩盖INCOMPLETE。

第二阶段：

- Nav2 Action短目标、反馈、成功、取消、失败测试。
- 单写入者约定、地图版本变化、断线行为有明确记录。
- 多目标队列不越过失败项，不与探索/RViz争抢。

交付：源码、README、启动命令、依赖清单、模拟测试结果、真实双机通信统计、实机测试结果及未完成项。未实测不要声称响应毫秒级或任何场景必定成功。

## 15. 现场参考命令与源码

在底盘录包（实际运动测试之前）：

```bash
source ~/ros2_ws/tools/robot_env.sh
bash ~/ros2_ws/tools/run_managed_mapping_diag.sh 0
```

Ctrl+C仅停止录包，不停止机器人。查看状态脚本同理：

```bash
python3 ~/ros2_ws/tools/watch_mapping_status.py
```

底盘参考源码：

- `/home/nvidia/ros2_ws/src/my_robot_mapping/scripts/map_session_manager.py`
- `/home/nvidia/ros2_ws/src/my_robot_mapping/scripts/map_versions.py`
- `/home/nvidia/ros2_ws/src/my_robot_mapping/launch/managed_mapping.launch.py`
- `/home/nvidia/ros2_ws/tools/robot_env.sh`

请先实施第一阶段，汇报实际ROS版本、网卡/IP、DDS配置、看到的服务/话题及状态，再开展需要运动的联调。不要把旧TCP命令名直接拼成不存在的ROS服务名。
