from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cloud.agent.web_search import (
    WebSearchError,
    ZhipuWebSearch,
)


from robot_tools.catalog import TOOL_SCHEMAS, TURN_ROUTE_SCHEMA
from robot_tools.weather import get_weather
from robot_tools.navigation import navigate_to
from robot_tools.music_aliases import add_alias
from robot_tools.catalog import MUSIC_ALIAS_SCHEMA
from robot_tools.registry import validate
import asyncio

@dataclass
class ToolCallBudget:
    # Paid search requests allowed
    # during ONE user turn.
    web_search_remaining: int = 1
    weather_remaining: int = 1


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
        if name == "get_weather":
            if budget is not None:
                if budget.weather_remaining <= 0:
                    return {"ok": False, "tool": name, "executed": False,
                            "status": "rejected", "reason": "per_turn_budget_exceeded"}
                budget.weather_remaining -= 1
            return await asyncio.to_thread(get_weather, **arguments)

        if name == "navigate_to":
            return self._navigate_to(
                arguments
            )

        if name == "music_alias_add":
            try:
                validate(arguments, MUSIC_ALIAS_SCHEMA)
            except ValueError:
                return {"ok": False, "tool": name, "status": "rejected",
                        "executed": False, "reason": "invalid_arguments"}
            return {"tool": name, **await asyncio.to_thread(add_alias, **arguments)}

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

    _navigate_to = staticmethod(navigate_to)
