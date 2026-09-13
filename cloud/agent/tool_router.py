from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cloud.agent.web_search import (
    WebSearchError,
    ZhipuWebSearch,
)


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
            "明确要求机器人前往地点选择 navigate_to。"
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
            },
            "required": [
                "action"
            ],
            "additionalProperties": False,
        },
    },
}


@dataclass
class ToolCallBudget:
    # Paid search requests allowed
    # during ONE user turn.
    web_search_remaining: int = 1


class ToolRouter:
    def __init__(
        self,
        *,
        web_search: (
            ZhipuWebSearch | None
        ) = None,
    ) -> None:
        self.web_search = (
            web_search
        )

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        budget: (
            ToolCallBudget | None
        ) = None,
    ) -> dict[str, Any]:
        if name == "navigate_to":
            return self._navigate_to(
                arguments
            )

        if name == "web_search":
            return await self._web_search(
                arguments,
                budget=budget,
            )

        return {
            "ok": False,
            "tool": name,
            "status": "rejected",
            "executed": False,
            "reason": "unknown_tool",
        }

    async def _web_search(
        self,
        arguments: dict[str, Any],
        *,
        budget: (
            ToolCallBudget | None
        ),
    ) -> dict[str, Any]:
        query = str(
            arguments.get(
                "query",
                "",
            )
        ).strip()

        recency = str(
            arguments.get(
                "recency",
                "noLimit",
            )
        ).strip()

        if not query:
            return {
                "ok": False,
                "tool": "web_search",
                "status": "rejected",
                "executed": False,
                "paid_requests": 0,
                "reason": "missing_query",
            }

        if len(query) > 70:
            return {
                "ok": False,
                "tool": "web_search",
                "status": "rejected",
                "executed": False,
                "paid_requests": 0,
                "reason": (
                    "query_too_long"
                ),
            }

        if (
            recency
            not in
            ZhipuWebSearch.RECENCY_VALUES
        ):
            return {
                "ok": False,
                "tool": "web_search",
                "status": "rejected",
                "executed": False,
                "paid_requests": 0,
                "reason": (
                    "invalid_recency"
                ),
            }

        if self.web_search is None:
            return {
                "ok": False,
                "tool": "web_search",
                "status": "unavailable",
                "executed": False,
                "paid_requests": 0,
                "reason": (
                    "web_search_not_configured"
                ),
            }

        if (
            budget is not None
            and
            budget.web_search_remaining
            <= 0
        ):
            print(
                "[TOOL] web_search "
                "rejected "
                "reason=per_turn_budget_exceeded",
                flush=True,
            )

            return {
                "ok": False,
                "tool": "web_search",
                "status": "rejected",
                "executed": False,
                "paid_requests": 0,
                "reason": (
                    "per_turn_budget_exceeded"
                ),
            }

        # Consume the budget immediately
        # before the paid network request.
        if budget is not None:
            budget.web_search_remaining -= 1

        try:
            search_result = (
                await self.web_search.search(
                    query,
                    recency=recency,
                )
            )

        except WebSearchError as exc:
            print(
                "[TOOL] web_search "
                f"error={exc}",
                flush=True,
            )

            return {
                "ok": False,
                "tool": "web_search",
                "status": "error",
                "executed": True,
                "paid_requests": 1,
                "query": query,
                "reason": str(exc),
            }

        results = search_result[
            "results"
        ]

        print(
            "[TOOL] web_search "
            f"query={query!r} "
            f"recency={recency} "
            f"results={len(results)} "
            "paid_requests=1",
            flush=True,
        )

        return {
            "ok": True,
            "tool": "web_search",
            "status": "success",
            "executed": True,
            "paid_requests": 1,
            "query": query,
            "recency": recency,
            "request_id": (
                search_result[
                    "request_id"
                ]
            ),
            "results": results,
        }

    @staticmethod
    def _navigate_to(
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        location = str(
            arguments.get(
                "location",
                "",
            )
        ).strip()

        if not location:
            return {
                "ok": False,
                "tool": "navigate_to",
                "status": "rejected",
                "executed": False,
                "reason": (
                    "missing_location"
                ),
            }

        result = {
            "ok": True,
            "tool": "navigate_to",
            "status": "mock_accepted",
            "executed": False,
            "location": location,
            "backend": "mock",
            "message": (
                f"已收到前往{location}的导航请求。"
                "当前仅完成 Tool Router 模拟调用，"
                "ROS2 导航执行尚未连接。"
            ),
        }

        print(
            "[TOOL] "
            f"navigate_to "
            f"location={location!r} "
            "backend=mock "
            "executed=false",
            flush=True,
        )

        return result
