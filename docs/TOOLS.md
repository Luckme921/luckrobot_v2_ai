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

配置 configs/tools.yaml 的 music_http.adapter=fallback 和 search_url；configs/audio.yaml 的 music.provider=http、music.enabled=true 才启用。当前测试分支已启用 music.enabled=true、music.provider=http。音频播放需要 gst-launch-1.0 和 PulseAudio。HTTP 后端支持暂停、恢复、停止，下一首/上一首尚无播放队列。

2026-09-19 Jetson 实测：QQ、网易云搜索返回 JSON，QQ 详情返回 stream.qqmusic.qq.com 音频地址；酷我证书过期，未关闭 TLS 校验。外部接口是否长期可用无法由一次测试保证。实测没有自动播放声音。

天气接口文档：https://open-meteo.com/en/docs 与 https://open-meteo.com/en/docs/geocoding-api 。

## 音乐请求修复（2026-09-19）

日志确认“播放一首稻香”已正确路由，但因音乐开关关闭而拒绝。现已启用 HTTP 后端。adapter=fallback 优先 QQ；搜索空列表或请求失败时尝试网页中的网易云接口。候选仍最多三首，播报歌名及歌手，用户选择后按来源解析地址；不会在选定歌曲失败后偷偷换成另一来源的同名歌曲。

网易云搜索：https://api.vkeys.cn/v2/music/netease ，参数 word/page/num；详情：https://api.qijieya.cn/meting/ ，参数 type=song/id。返回歌曲名称须与候选一致，地址限 HTTP(S)。两家搜索都出错会返回工具失败反馈。

QQ 对同一关键词曾临时返回空列表，稍后恢复；备用源用于降低这种故障影响。真实 QQ 音频已通过 GStreamer fakesink 完整解码（exit 0），未向音箱播放。此验证不证明现场音量和声学效果；网易云备用播放仍需独立验证。

## 可选自动播放（2026-09-20）

music_http.auto_play_enabled 默认 false，只有明确配置 true 才开启；auto_play_threshold 默认 90，auto_play_gap 默认 20。自动播放比较全部已返回候选并排序，不假定 API 顺序。要求 query 明确匹配歌手和完整歌名（如“周杰伦的稻香”），仅歌名继续询问。存在同名候选，或未指定版本却出现同曲不同版本时，也继续选择。分数是启发式匹配分，不是概率；供应商只返回部分搜索结果，因此不能证明全曲库唯一。

阈值有效范围 (0,100]，差值范围 [0,100]；无效范围不自动播放。复杂描述无法精确核实时保留候选交互。HTTP、QQ 的自动播放与手动选择都在实际播放前调用 before_playback 收尾过渡语；HTTP 地址解析仍与过渡语并行。该回调在 runtime 中连接 acknowledgements.finish。

## 本地点歌体验更新（2026-09-21，覆盖前述自动播放规则）

本地先匹配明确播放/暂停/继续和候选选择短句，命中时不调用 LLM。否定、解释性问句不在本地执行。匹配在现有 ASR/身份处理之后，因此不是完全零等待。

“播放一首歌”“随便放一首”“放点音乐”“每日推荐”用 music_http.random_queries 随机选一个搜索来源，再随机尝试最多三个候选，成功直接播放，失败明确反馈并清空候选；不反复让用户选择。该来源是配置的歌手/关键词池，不是平台每日推荐接口，不保证结果个性化或每次不重复。

已开启 auto_play_enabled。明确歌手+歌名时，比较返回的全部候选：歌手须匹配，歌名完全匹配或至少三字且相似度>=0.85；最佳候选与次佳相似度差小于0.1时仍询问。单独歌名/歌手继续选择，同名不同歌手时询问“你想听周杰伦，还是邓紫棋的呀？”。用户可说歌手、“第一首”或“随便”；单个候选也可说“好的”。原 auto_play_threshold/gap 是旧打分配置，新明确匹配规则不使用它们。

选择与自动播放均在实际播放前等待过渡语结束。播放器仍需现场验证；新逻辑本轮只在 Windows 本地测试，尚未部署设备。


新增 interaction.wake.barge_in_enabled 开关：最终回复合成/播报时允许 Lucky 打断，默认开启；打断清除待选歌曲、不撤销已执行工具。适用范围与现场验收见 OPERATIONS.md 的“Lucky 伪全双工试用”。

## 音乐并发搜索与模糊直播放（2026-09-22）

`music_http.adapter=fallback` 现在并发请求 Tang/QQ 与网易云两个已接入接口，而不是第一个有结果就停止。`search_limit` 控制每个接口最多候选数，默认 10；合并后 `pending_limit` 默认展示 5 首。接口失败彼此隔离，全部失败才返回服务不可用。仍不接受模型或用户直接提供的播放 URL。

明确包含歌手和歌名的请求会计算歌手与标题综合分并直接播放最高分；支持歌手简称，如“杰伦的龙卷风”。标题比较会忽略 Live、Mix、Remix、现场、版本、伴奏、DJ 等版本词，因此允许直接选择最相近版本。`fuzzy_auto_play_score` 默认 0.62，可提高以减少误播。只说歌名或歌手时仍保留候选选择，随机播放逻辑不变。
