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
            "你好，请看 链接",
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
