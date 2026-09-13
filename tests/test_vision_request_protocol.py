from __future__ import annotations

import unittest

from cloud.agent.client import (
    GLMAgent,
)
from cloud.agent.tool_router import (
    TOOL_SCHEMAS,
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
