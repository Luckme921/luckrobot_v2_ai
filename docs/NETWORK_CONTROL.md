# 双 Jetson 屏幕网络配置

2026-10-25。屏幕右上角“网络设置”管理两台设备的 Wi-Fi，默认 DHCP；
可分别填写静态 IPv4/前缀，统一网关和 DNS。两台静态地址必须不同。
列表选取 SSID 后输入密码，可同时配置小脑；上方显示两台设备的 Wi-Fi 和有线 IP。
触摸键盘支持英文大小写、数字、符号；中文 SSID 从扫描列表选取，不需要输入法。
本版支持开放网络、WPA/WPA2 Personal、WPA3 SAE；不支持企业 EAP 或网页认证。

## 已核实的拓扑

| 设备 | 用户 | Wi-Fi（当前） | 有线（固定） |
| --- | --- | --- | --- |
| 大脑 | jetson | 192.168.3.23 | 10.0.0.50/24 |
| 小脑 | nvidia | 192.168.3.32 | 10.0.0.51/24 |

Wi-Fi DHCP 后地址可能改变。设备管理通过有线连接；不修改有线 IP、网关或路由。
后续导航 RPC/ROS2 网关应绑定/连接 10.0.0.51，大脑使用 10.0.0.50。
当前 navigate_to 仍是 MOCK，本次没有下发真实运动指令。

## 调用与权限边界

QML NetworkPanel → 127.0.0.1:8765/api/network → Unix socket → NetworkManager。
大脑至小脑通过固定有线地址的 SSH 密钥，强制命令转发到小脑同一个 Unix socket。
不把网络配置注册为大模型工具，不允许模型构造 shell 命令。
密码仅在输入框、请求内存、加密 SSH 和 NetworkManager 中传递；不放入命令行、
日志、Git 或 job 状态。确认保存后，由 NetworkManager 正常保存 Wi-Fi 凭据。

- 系统辅助程序 `/usr/local/lib/luckrobot/network_agent.py` 必须 root 所有，不能从
  可由普通用户修改的项目路径以 root 启动。只接受 status/scan/apply/confirm/rollback。
- `luckrobot-network.service` 使用组可访问的 `/run/luckrobot-network/control.sock`，
  没有额外 TCP 监听端口，也不授予免密任意 sudo/nmcli。
- 硬性检查所选接口是 Wi-Fi。静态 Wi-Fi 网段不得覆盖脑间 10.0.0.0/24。
- `configs/network.yaml` 保存非敏感 peer 地址、用户名、密钥路径；
  `private/network/peer_ed25519`、`known_hosts` 仅存在大脑，不提交。
- 小脑 authorized_keys 使用 `restrict,command="/usr/bin/python3 /usr/local/lib/luckrobot/network_agent.py --client"`
  限制专用密钥；保留原有用户密钥。known_hosts 必须通过已信任 SSH 会话核对，不能盲目信任扫描结果。

## 配置事务

先验证全部参数、检查两台服务可达，再独立并发连接。每台仅为 Wi-Fi 建立
NetworkManager checkpoint，180 秒未确认自动回退。新连接在确认前不持久化。
一台连接失败时，另一台也请求回退；如回退响应丢失，等待 checkpoint 自动回退。
屏幕必须点击“确认保留连接”；点击“恢复原配置”主动回退。
这里不是跨设备原子事务：确认时若一台有线断开，可能只有另一台保存成功，
界面逐台报告结果，需恢复有线后检查。显示服务重启后可重新读取待确认 token。
确认只表示用户接受当前连接，不等于已经通过互联网访问测试。

## 安装和维护

```bash
# 在大脑项目根目录；小脑同样安装该 standalone 文件与安装脚本，用户名改 nvidia
sudo bash scripts/install_network_service.sh jetson wlP1p1s0
systemctl status luckrobot-network.service
printf '%s\n' '{"action":"status"}' | python3 /usr/local/lib/luckrobot/network_agent.py --client
```

安装脚本不切换 Wi-Fi，不修改 Ethernet，不切换桌面。小脑只需要系统 python3-dbus、
NetworkManager、该辅助程序和 service，无需部署整个机器人项目。
升级辅助程序后执行 `sudo systemctl restart luckrobot-network.service`。
现有无桌面 linuxfb 可直接运行；不必为此打开图形桌面。

核心文件：`edge/network/agent.py`（权限、参数、回退）、`bridge.py`（双机并发）、
`edge/display/server.py`（本机接口）、`NetworkPanel.qml`（面板）、
`NetworkField.qml`/`NetworkButton.qml`（控件）、`scripts/install_network_service.sh`。

参考 NetworkManager 官方 [Checkpoint API](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/gdbus-org.freedesktop.NetworkManager.html)。

## 验证记录

- 已在两台设备安装服务；大脑沿 10.0.0.51 的专用受限 SSH 密钥可查询小脑。
- 实测扫描成功，两台有线地址及当前 Wi-Fi 地址正确。
- 真实 NetworkManager 接受 DHCP/静态 IP 临时配置，checkpoint 主动回退成功。
  该检查跳过了激活新 Wi-Fi，不代表已验证换网及实际断线自动回退。
- Qt5 离屏加载、1280×720 布局已检查；触摸输入和实际换网仍需现场验收。
