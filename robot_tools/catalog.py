TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "navigate_to",
            "description": (
                "请求 LuckRobot 前往一个已知地点。"
                "只有用户明确要求机器人前往、带路、导航到"
                "某个地点时才调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": (
                            "用户要求前往的语义地点，"
                            "例如：实验室、客厅、厨房"
                        ),
                    }
                },
                "required": [
                    "location"
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "搜索互联网中的最新或实时信息。"
                "仅在问题需要今天、最近、最新、新闻、"
                "热点或其他可能变化的外部信息时调用。"
                "稳定的常识问题不要调用。"
                "音乐播放不要使用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "maxLength": 70,
                        "description": (
                            "简洁的搜索关键词或问题，"
                            "最多70个字符。"
                        ),
                    },
                    "recency": {
                        "type": "string",
                        "enum": [
                            "oneDay",
                            "oneWeek",
                            "oneMonth",
                            "oneYear",
                            "noLimit",
                        ],
                        "description": (
                            "搜索时间范围。"
                            "今天用oneDay，"
                            "最近一周用oneWeek，"
                            "一般信息用noLimit。"
                        ),
                    },
                },
                "required": [
                    "query"
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_vision",
            "description": (
                "当且仅当回答用户的问题必须观察 LuckRobot "
                "交互相机当前或最近几秒的画面时调用。"
                "普通聊天、身份、知识、新闻等不需要视觉的问题"
                "不要调用。"
                "询问当前物体、人物、环境、手中物品等使用 latest；"
                "询问刚才的动作、变化或最近发生了什么使用 recent。"
                "每一个新的当前、刚才或最近视觉问题都必须基于"
                "当前用户回合的新视觉证据。"
                "历史对话里的旧视觉描述不能替代本回合的"
                "request_vision。"
                "不要凭空猜测摄像头内容。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": [
                            "latest",
                            "recent",
                        ],
                        "description": (
                            "latest 表示当前画面；"
                            "recent 表示最近几秒多帧。"
                        ),
                    },
                    "seconds": {
                        "type": "number",
                        "minimum": 1,
                        "maximum": 5,
                        "description": (
                            "recent 模式回看秒数，"
                            "最大5秒。"
                        ),
                    },
                    "count": {
                        "type": "integer",
                        "minimum": 2,
                        "maximum": 5,
                        "description": (
                            "recent 模式均匀抽取帧数，"
                            "最多5帧。"
                        ),
                    },
                },
                "required": [
                    "mode"
                ],
                "additionalProperties": False,
            },
        },
    },

]


TURN_ROUTE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "route_turn",
        "description": (
            "对当前用户回合做唯一一次语义路由。"
            "必须依据当前真实需求选择动作。"
            "普通聊天选择 respond_text；"
            "需要观察当前或最近现实画面选择 request_vision；"
            "需要最新互联网信息选择 web_search；"
            "明确要求机器人前往地点选择 navigate_to；"
            "播放一首歌曲选择 play_music；推荐或找几首供选择选择 recommend_music；"
            "明确结束对话选择 end_conversation；"
            "暂停音乐选择 pause_music；"
            "继续音乐选择 resume_music；"
            "切换下一首选择 next_music；"
            "切换上一首选择 previous_music；"
            "停止音乐选择 stop_music。"
            "历史视觉描述不能替代当前回合新的视觉证据。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "respond_text",
                        "request_vision",
                        "web_search",
                        "navigate_to",
                        "play_music",
                        "recommend_music",
                        "end_conversation",
                        "pause_music",
                        "resume_music",
                        "next_music",
                        "previous_music",
                        "stop_music",
                    ],
                },
                "vision_mode": {
                    "type": "string",
                    "enum": [
                        "latest",
                        "recent",
                    ],
                },
                "seconds": {
                    "type": "number",
                    "minimum": 1,
                    "maximum": 5,
                },
                "count": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 5,
                },
                "query": {
                    "type": "string",
                    "maxLength": 70,
                },
                "recency": {
                    "type": "string",
                    "enum": [
                        "oneDay",
                        "oneWeek",
                        "oneMonth",
                        "oneYear",
                        "noLimit",
                    ],
                },
                "location": {
                    "type": "string",
                },
                "music_query": {
                    "type": "string",
                    "maxLength": 120,
                    "description": (
                        "play_music 时使用。"
                        "保留用户要求的歌手、歌名"
                        "或其他音乐搜索关键词。"
                    ),
                },
            },
            "required": [
                "action"
            ],
            "additionalProperties": False,
        },
    },
}



# Local tool schemas are the same contract used by Edge's registry.
LOCAL_SCHEMAS = {
    "fan_light_control": {
        "type": "object", "properties": {
            "action": {"type": "string", "enum": ["set_speed", "set_light", "light_off", "light_on", "status"]},
            "percent": {"type": "integer", "minimum": 0, "maximum": 100},
            "preset": {"type": "string", "enum": ["red_breath", "red_static", "blue_static", "rainbow"]},
            "mode": {"type": "string", "enum": ["static", "breath"]},
            "red": {"type": "integer", "minimum": 0, "maximum": 255},
            "green": {"type": "integer", "minimum": 0, "maximum": 255},
            "blue": {"type": "integer", "minimum": 0, "maximum": 255}},
        "required": ["action"], "additionalProperties": False},
    "volume_control": {
        "type": "object", "properties": {
            "action": {"type": "string", "enum": ["get", "set", "up", "down", "max"]},
            "percent": {"type": "integer", "minimum": 0, "maximum": 100}},
        "required": ["action"], "additionalProperties": False},
    "music_search": {
        "type": "object", "properties": {"query": {"type": "string", "maxLength": 120},
                                        "utterance": {"type": "string", "maxLength": 4000}},
        "required": ["query"], "additionalProperties": False},
    "music_select": {
        "type": "object", "properties": {"selection": {"type": "string", "maxLength": 120}},
        "required": ["selection"], "additionalProperties": False},
    "music_control": {
        "type": "object", "properties": {"action": {"type": "string", "enum":
            ["pause_music", "resume_music", "next_music", "previous_music", "stop_music"]}},
        "required": ["action"], "additionalProperties": False},
}
WEATHER_SCHEMA = {"type": "object", "properties": {
    "city": {"type": "string", "maxLength": 80},
    "days": {"type": "integer", "minimum": 1, "maximum": 7}},
    "required": ["city"], "additionalProperties": False}
TOOL_SCHEMAS.append({"type": "function", "function": {
    "name": "get_weather", "description": "查询指定城市今起最多七天的天气。地点不明确时 city 留空以询问用户。",
    "parameters": WEATHER_SCHEMA}})
MUSIC_ALIAS_SCHEMA = {"type": "object", "properties": {
    "kind": {"type": "string", "enum": ["artists", "songs"]},
    "canonical": {"type": "string", "maxLength": 60},
    "alias": {"type": "string", "maxLength": 60},
    "evidence": {"type": "string", "maxLength": 300}},
    "required": ["kind", "canonical", "alias", "evidence"],
    "additionalProperties": False}
TOOL_SCHEMAS.append({"type": "function", "function": {
    "name": "music_alias_add",
    "description": "仅在用户明确说出音乐别名，或联网搜索结果明确证明同一歌手/歌曲的中英文名、口语别称时，记录短别名供以后 QQ 音乐匹配。不得猜测；Live/Mix 是版本标记，不应把不同版本误写为别名。先完成搜索再提供来源摘要。",
    "parameters": MUSIC_ALIAS_SCHEMA}})
route_props = TURN_ROUTE_SCHEMA["function"]["parameters"]["properties"]
route_props["action"]["enum"].extend(["get_weather", "volume_control", "select_music", "fan_light_control"])
route_props.update({
    "city": {"type": "string", "maxLength": 80},
    "days": {"type": "integer", "minimum": 1, "maximum": 7},
    "volume_action": {"type": "string", "enum": ["get", "set", "up", "down", "max"]},
    "percent": {"type": "integer", "minimum": 0, "maximum": 100},
    "fan_light_action": {"type": "string", "enum": ["set_speed", "set_light", "light_off", "light_on", "status"]},
    "fan_light_percent": {"type": "integer", "minimum": 0, "maximum": 100},
    "fan_light_preset": {"type": "string", "enum": ["red_breath", "red_static", "blue_static", "rainbow"]},
    "fan_light_mode": {"type": "string", "enum": ["static", "breath"]},
    "fan_light_red": {"type": "integer", "minimum": 0, "maximum": 255},
    "fan_light_green": {"type": "integer", "minimum": 0, "maximum": 255},
    "fan_light_blue": {"type": "integer", "minimum": 0, "maximum": 255},
})
TURN_ROUTE_SCHEMA["function"]["description"] += (
    "天气选择 get_weather 并给出 city、days；音量选择 volume_control，"
    "提供 volume_action 和可选 percent；从刚才音乐候选中选择用 select_music，"
    "在 music_query 中保留编号或歌曲名。")
TURN_ROUTE_SCHEMA["function"]["description"] += (
    "明确要求调节散热风扇、切换风扇灯效或查询其状态时选择 fan_light_control；"
    "fan_light_action 为 set_speed/set_light/light_off/light_on/status。"
    "set_speed 提供 fan_light_percent；set_light 提供 fan_light_preset，"
    "可用 red_breath、red_static、blue_static、rainbow 预设，或提供"
    "fan_light_mode(static/breath) 和 fan_light_red/green/blue 三个 0..255 整数。"
    "用户要求黄色呼吸时使用 RGB=255,255,0 和 breath，不得改为红色。")
