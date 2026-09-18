from __future__ import annotations

import unittest

from cloud.agent.client import (
    GLMAgent,
    MusicRequest,
)
from cloud.agent.tool_router import (
    TURN_ROUTE_SCHEMA,
)


class MusicRequestProtocolTest(
    unittest.TestCase
):
    def test_route_schema_has_music_actions(
        self,
    ) -> None:
        action_schema = (
            TURN_ROUTE_SCHEMA[
                "function"
            ][
                "parameters"
            ][
                "properties"
            ][
                "action"
            ]
        )

        values = set(
            action_schema["enum"]
        )

        self.assertTrue(
            {
                "play_music",
                "pause_music",
                "resume_music",
                "next_music",
                "previous_music",
                "stop_music",
            }.issubset(values)
        )

    def test_play_music_route(
        self,
    ) -> None:
        route = (
            GLMAgent
            ._parse_turn_route_arguments(
                (
                    '{"action":"play_music",'
                    '"music_query":'
                    '"周杰伦 晴天"}'
                )
            )
        )

        request = route[
            "music_request"
        ]

        self.assertIsInstance(
            request,
            MusicRequest,
        )

        self.assertEqual(
            request.action,
            "play_music",
        )

        self.assertEqual(
            request.query,
            "周杰伦 晴天",
        )

    def test_play_music_allows_empty_query(
        self,
    ) -> None:
        route = (
            GLMAgent
            ._parse_turn_route_arguments(
                (
                    '{"action":'
                    '"play_music"}'
                )
            )
        )

        request = route[
            "music_request"
        ]

        self.assertIsInstance(
            request,
            MusicRequest,
        )

        self.assertEqual(
            request.action,
            "play_music",
        )

        self.assertEqual(
            request.query,
            "",
        )

    def test_pause_music_route(
        self,
    ) -> None:
        route = (
            GLMAgent
            ._parse_turn_route_arguments(
                (
                    '{"action":'
                    '"pause_music"}'
                )
            )
        )

        request = route[
            "music_request"
        ]

        self.assertEqual(
            request.action,
            "pause_music",
        )

        self.assertEqual(
            request.query,
            "",
        )

    def test_all_control_routes(
        self,
    ) -> None:
        for action in (
            "pause_music",
            "resume_music",
            "next_music",
            "previous_music",
            "stop_music",
        ):
            with self.subTest(
                action=action
            ):
                route = (
                    GLMAgent
                    ._parse_turn_route_arguments(
                        (
                            '{"action":"'
                            + action
                            + '"}'
                        )
                    )
                )

                self.assertEqual(
                    route[
                        "music_request"
                    ].action,
                    action,
                )


if __name__ == "__main__":
    unittest.main()
