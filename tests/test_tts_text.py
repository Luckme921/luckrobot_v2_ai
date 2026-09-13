import unittest

from edge.audio.tts.text import (
    normalize_for_speech,
    split_for_speech,
)


class TtsTextTest(unittest.TestCase):
    def test_normalize_wave_dash(self):
        self.assertEqual(
            normalize_for_speech(
                "你好～"
            ),
            "你好。",
        )

    def test_normalize_markdown_and_url(self):
        text = (
            "**你好**，请看 "
            "https://example.com/test"
        )

        result = (
            normalize_for_speech(
                text
            )
        )

        self.assertEqual(
            result,
            "你好，请看链接",
        )

    def test_split_long_spoken_reply(self):
        chunks = split_for_speech(
            (
                "我是 LuckRobot，"
                "可以陪你聊天、回答问题，"
                "也能帮你处理一些事情。"
            ),
            max_chars=16,
        )

        self.assertGreaterEqual(
            len(chunks),
            2,
        )

        self.assertTrue(
            all(
                len(item) <= 16
                for item in chunks
            )
        )


if __name__ == "__main__":
    unittest.main()


class TtsProsodyChunkingTest(
    unittest.TestCase
):
    def test_natural_robot_intro_chunks(
        self,
    ):
        text = (
            "我是 LuckRobot，"
            "由 哔哩哔哩 UP主 luckme "
            "开发的家用移动服务机器人，"
            "可以陪你聊天、帮你跑腿，"
            "还能陪你唠嗑解闷～"
        )

        chunks = split_for_speech(
            text,
            max_chars=36,
        )

        self.assertEqual(
            chunks,
            [
                "我是LuckRobot，",
                (
                    "由哔哩哔哩UP主luckme"
                    "开发的家用移动服务机器人，"
                ),
                (
                    "可以陪你聊天、帮你跑腿，"
                    "还能陪你唠嗑解闷。"
                ),
            ],
        )

    def test_soft_limit_never_hard_cuts_clause(
        self,
    ):
        clause = (
            "这是一个没有任何中间标点"
            "但语义应该连续说完的完整中文分句。"
        )

        chunks = split_for_speech(
            clause,
            max_chars=8,
        )

        self.assertEqual(
            chunks,
            [
                clause,
            ],
        )


class TtsSpacingNormalizationTest(
    unittest.TestCase
):
    def test_remove_spaces_around_chinese(
        self,
    ):
        text = (
            "我是 LuckRobot，由 哔哩哔哩 "
            "UP主 luckme 开发的家用移动服务机器人。"
        )

        self.assertEqual(
            normalize_for_speech(
                text
            ),
            (
                "我是LuckRobot，由哔哩哔哩"
                "UP主luckme开发的家用移动服务机器人。"
            ),
        )

    def test_keep_english_internal_space(
        self,
    ):
        self.assertEqual(
            normalize_for_speech(
                "我使用 OpenAI API 开发机器人。"
            ),
            "我使用OpenAI API开发机器人。",
        )
