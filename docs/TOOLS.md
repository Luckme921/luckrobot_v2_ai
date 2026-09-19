# 统一工具接口与音乐 API

更新：2026-09-19。

## 文件职责

robot_tools/catalog.py 定义云端和端侧工具参数 schema；registry.py 校验参数并计时；cloud.py 执行云端查询；edge.py 注册端侧函数。旧 cloud/agent/tool_router.py 保留兼容导入。

- weather.py:get_weather(city, days=1)：Open-Meteo 地名查询和天气查询；城市歧义时澄清，网络失败不编造数据。
- volume.py:volume_control(controller, action, percent=None)：音量查询、设置与调整。
- music.py:MusicTools.search / select / control：搜索、候选选择、播放控制。
- navigation.py:navigate_to(arguments)：MOCK 导航接口，实际运动接入前必须单独实现和验证。

模型只能选择注册工具并提交符合 schema 的参数。新增工具需同时更新 schema、路由、执行注册、失败反馈与测试。端侧执行结果返回 ok/status/executed/message 等字段；模型不能直接传 shell 或任意播放地址。

## 用户网页中的音乐接口

来源：用户提供的 wangye.html（只提取 API 协议，不执行网页脚本）。网页包含 QQ、网易云、咪咕、酷我四组接口。当前接入 QQ 的 Tang 适配器，保留原通用 HTTP 和 QQ 浏览器后端。

搜索：GET https://tang.api.s01s.cn/music_open_api.php?msg=歌曲关键词&type=json

返回数组，或 data 数组，字段 song_mid、song_title、singer_name。搜索结果不包含播放地址。

详情：同一接口传 msg、type=json、mid=选定歌曲的 song_mid。校验返回 song_mid 与候选一致，从 song_play_url_standard/hq 等字段取得地址；不自动选伴奏字段。歌曲元数据和播放地址只来自接口，不由大模型编造。

流程：用户点歌 → 最多三个候选 → 用户说第一首或完整歌名 → 用缓存 ID 查询详情 → GStreamer 播放。只在选择后请求详情，避免提前查询三个地址造成等待；有直接 URL 的通用后端直接用缓存 URL。候选 120 秒过期，结束对话/会话超时清除候选；重名时要求编号。

配置 configs/tools.yaml 的 music_http.adapter=tang 和 search_url；configs/audio.yaml 的 music.provider=http、music.enabled=true 才启用。此次保留设备原 enabled=false，避免未经现场验证改变默认音乐行为。音频播放需要 gst-launch-1.0 和 PulseAudio。HTTP 后端支持暂停、恢复、停止，下一首/上一首尚无播放队列。

2026-09-19 Jetson 实测：QQ、网易云搜索返回 JSON，QQ 详情返回 stream.qqmusic.qq.com 音频地址；酷我证书过期，未关闭 TLS 校验。外部接口是否长期可用无法由一次测试保证。实测没有自动播放声音。

天气接口文档：https://open-meteo.com/en/docs 与 https://open-meteo.com/en/docs/geocoding-api 。
