import unittest

from cloud.agent.client import (
    GLMAgent,
)


class AgentReplyTextTest(
    unittest.TestCase
):
    def test_bilibili_is_spoken_in_chinese(
        self,
    ):
        result = (
            GLMAgent
            ._normalize_reply_text(
                (
                    "我是 LuckRobot，"
                    "由 Bilibili UP主 luckme 开发。"
                )
            )
        )

        self.assertEqual(
            result,
            (
                "我是 LuckRobot，"
                "由 哔哩哔哩 UP主 luckme 开发。"
            ),
        )

        self.assertNotIn(
            "Bilibili",
            result,
        )


if __name__ == "__main__":
    unittest.main()
