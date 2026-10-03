# Jetson 本地 QQ 音乐 App 可行性（2026-10-03）

本分支为 `preview/QQmusic-APP`。设备为 Jetson Orin Nano，Ubuntu 22.04 / `arm64`，现有运行目录为 `/home/jetson/luckrobot_latency_test`。开始评估前，以本目录的 supervisor PID 停止对话进程，并停止 `luckrobot-display.service`；未修改生产/备份目录，也未提交设备配置、登录状态或日志。

用户指定的[QQ 音乐官方下载页](https://y.qq.com/download/download.html)列出 Linux 1.1.8（页面日期 2025-09-18）。其 Deb 链接文件名为 `qqmusic_1.1.8_amd64.deb`。2026-10-03 从该页面链接下载到设备 `/home/jetson/qqmusic-app-eval/`，`dpkg-deb -f` 确认 `Package: qqmusic`、`Version: 1.1.8`、`Architecture: amd64`；设备 `dpkg --print-architecture` 为 `arm64`。下载文件大小 75,662,164 字节，SHA-256 为 `42d18d6a8c3c17414e5b6dbc0c3ac893bb2540c1c5c09ce90d241843cc593788`。此包不能在 Jetson 上原生安装运行，故没有执行安装。

同页 AppImage 链接在设备上返回 HTTP 403，直接访问对应 CDN 路径也返回 403；当前没有可验证的 ARM64 官方包。此结论只覆盖该官方下载页在测试日期展示的版本。若官网以后提供 ARM64 包，必须重新核对架构、依赖、登录、音频输出、无桌面运行方式及可编程搜索/选曲/控制接口后再切换。

现有音乐实现是 `edge/music/qqmusic.py` 的已登录 Firefox 网页控制，`robot_tools/music.py` 对外暴露搜索、选曲与播放控制。桌面 App 即使能运行，也不能自动认为它提供等价的搜索结果、精确选曲、当前曲目和播放状态接口。适配器必须先通过真实设备验收，才可替换浏览器后端；目前代码和 `configs/audio.yaml` 保持原状。

## 第三方 ARM64 客户端评估

用户已同意评估第三方 ARM64 客户端。候选为 [YAQMC v0.1.0](https://github.com/YAQMC/YAQMC/releases/tag/v0.1.0)，这是独立的开源 QQ 音乐客户端，并非腾讯官方 App。已将 `YAQMC-linux-arm64.deb` 下载到设备的 `/home/jetson/qqmusic-app-eval/`。`dpkg-deb -f` 确认包名 `yaqmc`、版本 `0.1.0`、架构 `arm64`；99,831,192 字节文件的 SHA-256 为 `88c37f5b8987ce0d695c1e1c805bd4ce2268afefc2f594de11d9e6f3c4aaf21e`，与 GitHub Release 资产标注一致。仅下载并核验，尚未安装、登录或将其接入机器人。

YAQMC 文档说明它支持 QQ/微信 OAuth 登录、搜索目录及播放，但这些是图形应用内功能。[本地 HTTP API 文档](https://github.com/YAQMC/YAQMC/blob/v0.1.0/docs/zh-CN/local-api.md)公开的是播放状态、当前曲目、队列读取、暂停/继续、上一首/下一首、音量等接口，**没有搜索目录、选择搜索结果、将指定歌曲加入队列的接口**。该 API 还需要先在图形界面开启并取得 bearer token。仅凭现有接口，机器人不能完成“播放刘欢的《从头再来》”这类指定曲目的语音请求；将现有 Firefox 后端换为 YAQMC 会使核心功能退化。不能通过给模型任意 URL、shell 命令或依赖不稳定的鼠标坐标来填补这一接口缺口。

设备当前默认启动目标为 `multi-user.target`，SSH 环境中没有 `DISPLAY` 或 `WAYLAND_DISPLAY`；现有表情显示用独占 framebuffer。YAQMC 安装包包含 Electron/GTK 图形程序，因此图形登录、屏幕占用以及与表情显示共存，都需要单独进行设备测试。当前 QQ 音乐网页的登录状态也不能推定会自动迁移到 YAQMC。YAQMC 项目明确说明不绕过账号权限，会员内容仍需以实际账号做播放验收。

**当前决策：**保留现有浏览器音乐后端和配置，暂不安装或切换 YAQMC。若后续要切换，先取得或实现稳定的“搜索 → 候选 → 指定曲目入队/播放”受限接口，并在设备上验收登录、会员播放、当前曲目同步、音频路由和显示共存，再实现新的适配器。评估包放在设备独立目录，不进入 Git；可在评估结束后删除。
