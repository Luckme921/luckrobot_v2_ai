from __future__ import annotations

from typing import Any


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
    }
]


class ToolRouter:
    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if name == "navigate_to":
            return self._navigate_to(
                arguments
            )

        return {
            "ok": False,
            "tool": name,
            "status": "rejected",
            "executed": False,
            "reason": "unknown_tool",
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
                "reason": "missing_location",
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
