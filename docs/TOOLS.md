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

HTTP 备用后端由 configs/tools.yaml 的 music_http.adapter=fallback 和 search_url 配置；设 configs/audio.yaml 的 music.provider=http、music.enabled=true 时启用。音频播放需要 gst-launch-1.0 和 PulseAudio。HTTP 后端支持暂停、恢复、停止，下一首/上一首尚无播放队列。

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

“搜一下邓紫棋的歌”“邓紫棋的歌”会直接按歌手搜索；“换歌”“再找一首歌曲”
和“下一首”在 HTTP 后端没有播放队列时按随机偏好重新搜索并直接播放。上述短句不会
先交给模型，也不会再落入缺少音乐提示词的保护回复。

“播放一首歌”“随便放一首”“放点音乐”“每日推荐”属于通用随机请求，成功后直接
播放，失败明确反馈并清空候选，不反复让用户选择。`music_http.random_queries` 现在只
是偏好文件没有可用配置时的兼容后备项，不是平台每日推荐接口。

2026-09-24 起，随机音乐优先读取 `configs/music_preferences.yaml`。其中
`preferred_tracks` 配置常听的歌手和歌曲，`preferred_artists` 只作为曲目全部失败后的
后备搜索；`search_attempts` 限制不同偏好搜索次数，`candidate_play_attempts` 限制同一
搜索结果的播放尝试。完整随机请求会清除上一轮候选并直接播放，不进入选择流程。
已经覆盖现场 ASR 文本“放一首音乐，随便播放一首就可以”和
“随便播放一首歌就可以”。用户只回答“随便/都行”时，仍表示从当前候选中任选一首。

已开启 auto_play_enabled。明确歌手+歌名时，比较返回的全部候选：歌手须匹配，歌名完全匹配或至少三字且相似度>=0.85；最佳候选与次佳相似度差小于0.1时仍询问。单独歌名/歌手继续选择，同名不同歌手时询问“你想听周杰伦，还是邓紫棋的呀？”。用户可说歌手、“第一首”或“随便”；单个候选也可说“好的”。原 auto_play_threshold/gap 是旧打分配置，新明确匹配规则不使用它们。

选择与自动播放均在实际播放前等待过渡语结束。2026-09-24 已部署到
`/home/jetson/luckrobot_latency_test`，设备端单元测试和音频运行时启动通过；随机播放的
实际听感仍由现场语音请求验收。


新增 interaction.wake.barge_in_enabled 开关：最终回复合成/播报时允许 Lucky 打断，默认开启；打断清除待选歌曲、不撤销已执行工具。适用范围与现场验收见 OPERATIONS.md 的“Lucky 伪全双工试用”。

## 音乐并发搜索与模糊直播放（2026-09-22）

`music_http.adapter=fallback` 现在并发请求 Tang/QQ 与网易云两个已接入接口，而不是第一个有结果就停止。`search_limit` 控制每个接口最多候选数，默认 10；合并后 `pending_limit` 默认展示 5 首。接口失败彼此隔离，全部失败才返回服务不可用。仍不接受模型或用户直接提供的播放 URL。

## wangye.html 中的公开音乐接口

页面包含四组搜索/详情调用。这些均为第三方公开接口，项目无法保证长期稳定性、服务
条款或曲目授权，生产逻辑只能把它们当作可替换的数据源。

- 咪咕搜索：`GET https://api.xcvts.cn/api/music/migu?gm=<关键词>&n=&num=<数量>&type=json`。
  返回 `code=200` 和 `data[]`；播放详情继续请求同一地址，把 `n` 设置为搜索结果序号，
  读取 `music_url`、`lrc_url`、`cover`。当前机器人尚未接入此来源。
- 网易云搜索：`GET https://api.vkeys.cn/v2/music/netease?word=<关键词>&page=1&num=<数量>`，
  从 `data[]` 读取 `id/song/singer/album/cover`。播放详情调用
  `GET https://api.qijieya.cn/meting/?type=song&id=<歌曲ID>`，读取数组首项的
  `url/name/artist/pic`；歌词调用 vkeys 的 `/v2/music/netease/lyric?id=<歌曲ID>`。
  当前机器人已接入搜索和播放详情，没有在语音流程中使用歌词。
- QQ 搜索：`GET https://tang.api.s01s.cn/music_open_api.php?msg=<关键词>&type=json`，
  返回数组或 `{data: [...]}`，主要字段为 `song_mid/song_title/singer_name`。详情在同一
  请求上增加 `mid=<song_mid>`，读取 `song_play_url_standard`、`song_play_url_hq`、
  `song_play_url` 等。当前机器人已接入，并校验详情返回的 `song_mid` 必须与选择一致。
- 酷我搜索：`GET https://kw-api.cenguigui.cn/?name=<关键词>&page=1&limit=<数量>`，
  读取 `data[].rid/name/artist/album/pic`。详情请求增加
  `id=<rid>&type=song&level=zp&format=json`，播放地址位于 `data.url`。当前机器人尚未
  接入此来源。

只读通断检查：

```bash
.venv/bin/python scripts/check_music_apis.py
.venv/bin/python scripts/check_music_apis.py "宋冬野 安河桥" --limit 10
```

脚本只检查搜索、JSON 结构、详情和播放地址是否存在，不下载或播放音频，并列出各来源返回的
歌曲 ID、歌名和歌手；不会打印播放地址。结果中的
`reachable=true` 表示本次调用成功，不代表以后持续可用。

2026-09-24 在 Jetson 以“周杰伦 晴天”探测：网易云搜索、详情与歌词可用，QQ 搜索与
详情可用；咪咕能建立 HTTP 请求但返回结构不符合页面约定，酷我因服务端证书过期而
无法建立可信 TLS 连接。机器人当前使用的网易云和 QQ 两个来源均通过本次探测。

明确包含歌手和歌名的请求会计算歌手与标题综合分并直接播放最高分；支持歌手简称，如“杰伦的龙卷风”。标题比较会忽略 Live、Mix、Remix、现场、版本、伴奏、DJ 等版本词，因此允许直接选择最相近版本。`fuzzy_auto_play_score` 默认 0.62，可提高以减少误播。只说歌名或歌手时仍保留候选选择，随机播放逻辑不变。

## 自然点歌与候选选择（2026-09-24）

现场日志中的“我想听我想听宋冬野的安河桥”由本地规则处理，不调用 LLM。重复的请求前缀
会先清理，“某某的某某歌”拆为“歌手 歌名”，再提交给 QQ/Tang 与网易云并发搜索；
“你可以放一首歌吗”也直接
进入随机播放，不再让模型搜索字面歌曲《一首歌》。多来源结果按歌手、歌名相关度统一
排序，不能再由网络返回先后决定前五项。

候选提示使用“歌手的《歌名/版本》”自然描述，不要求用户记编号；“第三首”仍兼容。
等待选择期间，候选歌手、完整歌名、去版本歌名和“吉他版/DJ版/翻唱”等版本词用于本地
上下文匹配。SenseVoice 的 sherpa-onnx SenseVoice 接口没有动态 hotword 参数，因此这是
ASR 文本后的候选上下文校正，不应写成修改了声学模型词表；本地仍无法唯一对应时才交给
LLM 路由。

2026-09-24 的“第三首”失败为 `ValueError`：网易云搜索标题可能是
“莉莉安(翻自宋冬野)”，详情标题只有“莉莉安”，旧代码要求两个字符串完全相同而拒绝
播放。现在对同一数字歌曲 ID 允许去掉翻唱/版本标注后的标题匹配；真正不相关的标题仍
拒绝。地址解析或播放器失败会记录 `MUSIC RESOLVE_FAILED/PLAY_FAILED` 的来源、歌曲和
原因，并向用户说明是哪首歌暂时拿不到地址，而不是统一返回“操作没有完成”。

旧版 `luckrobot_release/edge/music/qqmusic.py` 使用 Selenium、Firefox 和已登录的持久化
profile 打开 QQ 音乐网页搜索/播放器；它不是 H5 OpenID API。设备上旧 profile 位于
`/home/jetson/luckrobot_release/private/qqmusic-firefox`，Firefox 与 geckodriver 仍存在，
但 profile/cookie 属于 private 数据，禁止复制进 Git。

2026-09-30 在测试目录 `/home/jetson/luckrobot_latency_test/private/qqmusic-firefox`
新建独立 Firefox profile，用户在 Jetson 图形桌面完成 QQ 音乐登录。无桌面 Selenium
随后搜索“邓紫棋”返回 5 首候选；按歌曲 ID 打开并播放《泡沫》，播放器及音频路由完成，
测试后已停止。因此 `configs/audio.yaml` 在测试分支改用 `music.provider: qqmusic`。
这是控制已登录的 QQ 音乐网页，仍不是 QPlay/OpenAPI；手机会员权益是否覆盖所有指定歌曲，
需按曲目现场验证。首次启用时暂关个人歌单后台刷新，以免它占用浏览器锁影响点歌延迟。
网页后端失效时可把 `music.provider` 改回 `http` 并重启机器人。
图形桌面退出或 Firefox 崩溃后，Selenium 可能保留已失效的 session ID；下一次
`search_candidates` / `play` 遇到该错误，或 geckodriver 本地连接断开时，会关闭旧
WebDriver、重建浏览器并重试一次，
日志记录 `[MUSIC] QQ_SESSION_RESTART`。连续失败仍向用户明确报错，不会无限重试。
QQ 网页搜索候选同时提取歌曲行中的歌手，用于偏好歌单的“歌手 + 歌名”校验；
否则随机播放会因所有候选歌手为空而全部被过滤。
语音点歌识别包含“我想要听 / 想要听”。针对实际出现的“孙冬野南河桥”误识别，
仅在明确点歌句式中将其纠正为“宋冬野 安和桥”；单独说出该短语不会触发点歌。
“宋冬野的安河桥”等已知同音误识别也会在 QQ 搜索前改为正式歌名“安和桥”，
避免误选《安河桥（伴奏）》。随机点歌在当前进程内避开最近四首已播的配置曲目；
重启后此记录清空。音量控制支持“我想加大点音量”，pactl 调用最多等待 3 秒，
超时返回工具错误。休眠状态仍须先唤醒 Lucky 才处理音量命令。
明确点歌优先在本地解析“歌手 + 歌名”，把常见 ASR 误识别（宋东野、松农野、
安河桥）规范为 QQ 可搜索的“宋冬野 安和桥”，再搜索、校验歌手与歌名并播放。
QQ 返回了不相关列表时不再读出候选；只有没有明确点歌结构的语句才走模型路由。
模型不能只口头承诺播放：真正播放必须由 music_search 工具成功返回。
QQ 播放器会暂停所有旧播放页；PulseAudio sink-input 短暂消失时重新枚举再迁移。
QQ 播放器切换下一首或上一首时，工具用播放器返回的实际曲目信息更新
`current_song` 和屏幕，不再沿用最初点播歌曲的标题；日志打印
`[MUSIC] NOW_PLAYING`，可对照 QQ 实际播放与屏幕显示。若播放器没有返回曲目信息，
切歌后清空旧歌名，避免错误显示。
若最终仍未确认播放，停止播放器、清除候选并记录 QQ_PLAY_FAILED 的异常原因。
“关闭音乐 / 停止播放 / 关掉音乐 / 别放了”等短句优先映射到
`music_control(action=stop_music)`，即使正在等待选歌也不当歌名搜索。
播放音乐时仍处于唤醒等待状态，先喊 Lucky，再说停止命令。
“有什么推荐的歌曲吗”现在从 `configs/music_preferences.yaml` 给出三首熟悉曲目，
不把“有什么推荐”送到 QQ 当歌名搜索。用户选中其中一首后才用其歌手和歌名
搜索 QQ 并校验匹配；“上次搜到的某歌手那首”优先匹配当前候选，避免重搜。
未过期的候选列表会以编号、歌名和歌手作为本轮临时上下文传给语义路由器；
本地无法识别的“奶袜的那首”等说法应路由到 `select_music`，由端侧按编号从原候选
中播放，不重新用误识别的词搜索 QQ。日志的 `[MUSIC] ROUTE_CANDIDATES` 可核对
这次实际给模型的列表；候选过期或会话结束后清空。换歌或“再找点其他歌”走随机
歌单，不能将“随便”作为 QQ 歌名搜索。
明确歌手和歌名、常见点歌句式优先本地解析；本地不认识的表达才走模型路由。
目前 QQ 搜索无可信候选时由工具返回未找到，**尚未**自动让模型改写歌名再搜索。
没有可用候选且用户只记得歌词、部分描述或“上次搜到的那首”时，
本地不凭这些词直接搜索 QQ，而交给模型结合对话上下文判断；模型只能提交
音乐搜索请求，不能仅用自然语言宣称播放成功。

QQ 音乐开发者平台的 H5 接入属于 QPlay Auth 登录鉴权：需要先注册应用取得 appId/appKey、
配置 callback，通过授权得到 openID/openToken，再申请相应 OpenAPI 权限。扫码/H5 授权本身
不等于获得曲库搜索、VIP 播放地址或规避版权限制，不能直接替换当前播放器。接入前还需
确认应用审核、设备形态、允许的播放能力和 token 存储方式；密钥与 token 只进入设备私有
配置。

`music_http.log_candidates=true` 时，运行日志会增加 `[MUSIC] SEARCH_RESULTS`，记录每个来源
实际收到的组合查询词及候选元数据，不记录播放 URL。`[TOOL_REQUEST]` 同时记录请求来自
`local` 本地规则还是 `model` 模型路由，以及传给音乐工具的参数。当前音乐路由使用单一
`music_query`，没有独立的“歌手”和“歌名”API 字段；例如“我想听宋冬野的安河桥”由本地
规则整理为 `query="宋冬野 安河桥"`，再把同一查询词交给各搜索源。模型无法被本地规则匹配
时，云端日志的 `[ROUTE] action=play_music music_query=...` 会保留模型实际生成的查询词。

Tang/QQ 第三方端点对中文组合关键词有额外兼容处理：本地意图及排序仍使用“宋冬野 安河桥”，
实际提交给该端点的 `msg` 会压缩为“宋冬野安河桥”。2026-09-24 实测紧凑形式返回了宋冬野的
《安和桥》，而带空格形式曾返回空列表；网易源继续使用带空格形式。接口返回标题与用户说法有
一字差异时仍需同时匹配歌手和模糊标题，不能仅凭标题直接播放。

2026-09-24 Jetson 现场复测“宋冬野 安河桥”：Tang/QQ 公共接口本次返回空列表，网易云公开
搜索只返回翻唱、DJ 或其他版本，没有返回宋冬野原唱。这只能说明当前第三方接口在本次请求中
没有提供原唱，不能据此判断 QQ 音乐正式曲库中不存在该歌曲。旧版 Firefox profile 的副本也已
做只读搜索验证：页面跳转到新版 `ryqq_v2` 搜索页，显示“登录”，并且没有生成可用的歌曲详情
链接，说明旧 cookie 已失效；当时没有把 Selenium 后端接入正式流程。2026-09-30 用户在
测试目录的新 profile 重新登录后，搜索和一次短播放已通过。网页结构及播放权限仍可能变化。

QPlay Auth 官方文档中的扫码流程适合车机、带屏音箱等设备：先取得二维码、约每秒轮询授权
状态，再由服务端用授权码换取 token；H5 流程则需要 appId、签名参数、包名和 callbackUrl。
两种流程都依赖已审核的开发者应用与获批的 OpenAPI 能力。项目在取得这些前置条件之前不保存
占位密钥，也不把 H5 登录页误当成音乐搜索或播放 API。
