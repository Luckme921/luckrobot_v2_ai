from __future__ import annotations

import unittest

from cloud.agent.client import (
    GLMAgent,
)
from cloud.agent.tool_router import (
    TOOL_SCHEMAS,
    TURN_ROUTE_SCHEMA,
)


class VisionRequestProtocolTest(
    unittest.TestCase
):
    def test_schema_is_available(
        self,
    ) -> None:
        names = {
            schema["function"]["name"]
            for schema in TOOL_SCHEMAS
        }

        self.assertIn(
            "request_vision",
            names,
        )

    def test_latest_request(
        self,
    ) -> None:
        request = (
            GLMAgent
            ._parse_vision_request_arguments(
                '{"mode":"latest"}'
            )
        )

        self.assertEqual(
            request.mode,
            "latest",
        )
        self.assertEqual(
            request.seconds,
            0.0,
        )
        self.assertEqual(
            request.count,
            1,
        )

    def test_recent_request(
        self,
    ) -> None:
        request = (
            GLMAgent
            ._parse_vision_request_arguments(
                (
                    '{"mode":"recent",'
                    '"seconds":4,'
                    '"count":3}'
                )
            )
        )

        self.assertEqual(
            request.mode,
            "recent",
        )
        self.assertEqual(
            request.seconds,
            4.0,
        )
        self.assertEqual(
            request.count,
            3,
        )

    def test_no_current_visual_evidence_prompt(
        self,
    ) -> None:
        prompt = (
            GLMAgent
            ._current_turn_visual_state_prompt(
                False
            )
        )

        self.assertIn(
            "CURRENT_TURN_VISUAL_EVIDENCE=none",
            prompt,
        )

        self.assertIn(
            "必须通过 route_turn 选择 request_vision",
            prompt,
        )

        self.assertIn(
            "只能代表过去",
            prompt,
        )

    def test_attached_visual_evidence_prompt(
        self,
    ) -> None:
        prompt = (
            GLMAgent
            ._current_turn_visual_state_prompt(
                True
            )
        )

        self.assertIn(
            "CURRENT_TURN_VISUAL_EVIDENCE=attached",
            prompt,
        )

        self.assertIn(
            "本回合选择的新视觉证据",
            prompt,
        )


    def test_route_turn_schema(
        self,
    ) -> None:
        self.assertEqual(
            TURN_ROUTE_SCHEMA[
                "function"
            ][
                "name"
            ],
            "route_turn",
        )

    def test_route_turn_respond_text(
        self,
    ) -> None:
        route = (
            GLMAgent
            ._parse_turn_route_arguments(
                '{"action":"respond_text"}'
            )
        )

        self.assertEqual(
            route["action"],
            "respond_text",
        )

        self.assertNotIn(
            "reply",
            route,
        )

    def test_route_turn_recent_vision(
        self,
    ) -> None:
        route = (
            GLMAgent
            ._parse_turn_route_arguments(
                (
                    '{"action":"request_vision",'
                    '"vision_mode":"recent",'
                    '"seconds":4,'
                    '"count":3}'
                )
            )
        )

        request = route[
            "vision_request"
        ]

        self.assertEqual(
            request.mode,
            "recent",
        )

        self.assertEqual(
            request.seconds,
            4.0,
        )

        self.assertEqual(
            request.count,
            3,
        )

    def test_route_messages_use_previous_user_only(
        self,
    ) -> None:
        messages = (
            GLMAgent
            ._build_route_messages(
                "CURRENT_USER",
                [
                    {
                        "role": "user",
                        "content": "OLD_USER",
                    },
                    {
                        "role": "assistant",
                        "content": "OLD_ASSISTANT",
                    },
                    {
                        "role": "user",
                        "content": "RECENT_USER",
                    },
                    {
                        "role": "assistant",
                        "content": "RECENT_ASSISTANT",
                    },
                ],
            )
        )

        self.assertEqual(
            len(messages),
            2,
        )

        self.assertEqual(
            [
                item["role"]
                for item in messages
            ],
            [
                "system",
                "user",
            ],
        )

        joined = "\n".join(
            str(
                item["content"]
            )
            for item in messages
        )

        self.assertNotIn(
            "OLD_USER",
            joined,
        )
        self.assertNotIn(
            "OLD_ASSISTANT",
            joined,
        )
        self.assertNotIn(
            "RECENT_ASSISTANT",
            joined,
        )
        self.assertIn(
            "RECENT_USER",
            joined,
        )
        self.assertIn(
            "CURRENT_USER",
            joined,
        )

    def test_invalid_mode(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            (
                GLMAgent
                ._parse_vision_request_arguments(
                    '{"mode":"unknown"}'
                )
            )


if __name__ == "__main__":
    unittest.main()
