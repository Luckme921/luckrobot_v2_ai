import unittest

from cloud.agent.tool_router import (
    ToolCallBudget,
    ToolRouter,
)


class FakeWebSearch:
    def __init__(self):
        self.calls = 0

    async def search(
        self,
        query,
        *,
        recency="noLimit",
    ):
        self.calls += 1

        return {
            "request_id": "fake-request",
            "query": query,
            "recency": recency,
            "results": [
                {
                    "title": "测试新闻",
                    "content": "测试内容",
                    "link": "",
                    "media": "",
                    "publish_date": (
                        "2026-09-13"
                    ),
                }
            ],
        }


class WebSearchToolTest(
    unittest.IsolatedAsyncioTestCase
):
    async def test_search_success(self):
        search = FakeWebSearch()

        router = ToolRouter(
            web_search=search
        )

        budget = ToolCallBudget(
            web_search_remaining=1
        )

        result = await router.execute(
            "web_search",
            {
                "query": "今天科技新闻",
                "recency": "oneDay",
            },
            budget=budget,
        )

        self.assertTrue(
            result["ok"]
        )

        self.assertEqual(
            result["paid_requests"],
            1,
        )

        self.assertEqual(
            search.calls,
            1,
        )

        self.assertEqual(
            budget.web_search_remaining,
            0,
        )

    async def test_second_search_rejected(
        self,
    ):
        search = FakeWebSearch()

        router = ToolRouter(
            web_search=search
        )

        budget = ToolCallBudget(
            web_search_remaining=1
        )

        first = await router.execute(
            "web_search",
            {
                "query": "今天科技新闻",
                "recency": "oneDay",
            },
            budget=budget,
        )

        second = await router.execute(
            "web_search",
            {
                "query": "今天国际新闻",
                "recency": "oneDay",
            },
            budget=budget,
        )

        self.assertTrue(
            first["ok"]
        )

        self.assertFalse(
            second["ok"]
        )

        self.assertEqual(
            second["reason"],
            (
                "per_turn_budget_exceeded"
            ),
        )

        # Critical cost-control check:
        # only ONE real search method call.
        self.assertEqual(
            search.calls,
            1,
        )

    async def test_missing_query_is_free(
        self,
    ):
        search = FakeWebSearch()

        router = ToolRouter(
            web_search=search
        )

        budget = ToolCallBudget(
            web_search_remaining=1
        )

        result = await router.execute(
            "web_search",
            {},
            budget=budget,
        )

        self.assertFalse(
            result["ok"]
        )

        self.assertEqual(
            result["paid_requests"],
            0,
        )

        self.assertEqual(
            search.calls,
            0,
        )

        self.assertEqual(
            budget.web_search_remaining,
            1,
        )


if __name__ == "__main__":
    unittest.main()
