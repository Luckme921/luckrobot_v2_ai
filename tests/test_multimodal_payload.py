from __future__ import annotations

import base64
import unittest

from cloud.agent.client import (
    GLMAgent,
)
from edge.agent.cloud_client import (
    CloudAgentClient,
    CloudAgentError,
)


JPEG = (
    b"\xff\xd8"
    b"luckrobot-vision"
    b"\xff\xd9"
)


class MultimodalPayloadTest(
    unittest.TestCase
):
    def test_agent_text_only_content(
        self,
    ) -> None:
        content = (
            GLMAgent
            ._build_user_content(
                "你好",
                None,
            )
        )

        self.assertEqual(
            content,
            "你好",
        )

    def test_agent_multimodal_content(
        self,
    ) -> None:
        url = (
            "data:image/jpeg;base64,"
            "AAAA"
        )

        content = (
            GLMAgent
            ._build_user_content(
                "看一下",
                [url],
            )
        )

        self.assertIsInstance(
            content,
            list,
        )

        self.assertEqual(
            content[0]["type"],
            "text",
        )

        self.assertEqual(
            content[0]["text"],
            "看一下",
        )

        self.assertEqual(
            content[1]["type"],
            "image_url",
        )

        self.assertEqual(
            content[1][
                "image_url"
            ]["url"],
            url,
        )

    def test_edge_encodes_jpeg(
        self,
    ) -> None:
        encoded = (
            CloudAgentClient
            ._encode_jpeg_frames(
                [JPEG]
            )
        )

        self.assertEqual(
            len(encoded),
            1,
        )

        self.assertEqual(
            base64.b64decode(
                encoded[0]
            ),
            JPEG,
        )

    def test_edge_rejects_invalid_jpeg(
        self,
    ) -> None:
        with self.assertRaises(
            CloudAgentError
        ):
            (
                CloudAgentClient
                ._encode_jpeg_frames(
                    [b"not-a-jpeg"]
                )
            )

    def test_edge_rejects_too_many(
        self,
    ) -> None:
        with self.assertRaises(
            CloudAgentError
        ):
            (
                CloudAgentClient
                ._encode_jpeg_frames(
                    [JPEG] * 6
                )
            )


if __name__ == "__main__":
    unittest.main()
