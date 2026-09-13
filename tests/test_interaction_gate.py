import unittest

from edge.audio.wake.session import (
    InteractionGate,
)


def create_gate() -> InteractionGate:
    return InteractionGate(
        wake_command_timeout_seconds=8.0,
        normal_timeout_seconds=12.0,
        chat_timeout_seconds=20.0,
        transcript_aliases=[
            "lucky",
            "luck",
            "拉可",
            "拉ucky",
            "拉uckk",
            "阿k",
            "l克",
            "那可",
            "那可以",
            "拉克",
            "拉uck克",
            "那uck克",
            "老uck克",
            "老克",
        ],
        transcript_exact_aliases=[
            "拉",
            "拉克",
            "那可",
            "那可以",
            "拉uck克",
            "那uck克",
            "拉ucky",
            "老uck克",
            "老克",
            "拉客",
            "那克",
        ],
        chat_mode_triggers=[
            "陪我聊",
            "聊聊天",
        ],
        sleep_phrases=[
            "不聊了",
            "先这样吧",
            "你休息吧",
        ],
        emergency_stop_phrases=[
            "停",
            "停止",
            "别动",
        ],
    )


class InteractionGateTest(
    unittest.TestCase
):
    def test_sleeping_ignores_text(self):
        gate = create_gate()

        result = gate.process(
            "今天天气不错",
            now=0.0,
        )

        self.assertEqual(
            result.action,
            "ignore",
        )

    def test_kws_wakes_gate(self):
        gate = create_gate()

        gate.on_wake(
            now=0.0,
        )

        self.assertEqual(
            gate.state,
            gate.AWAKE_WAIT_COMMAND,
        )

    def test_wake_echo_only(self):
        gate = create_gate()

        gate.on_wake(
            now=0.0,
        )

        result = gate.process(
            "lucky。",
            now=1.0,
        )

        self.assertEqual(
            result.action,
            "awake",
        )

    def test_same_utterance_command(self):
        gate = create_gate()

        gate.on_wake(
            now=0.0,
        )

        result = gate.process(
            "lucky带我去厨房。",
            now=1.0,
        )

        self.assertEqual(
            result.command,
            "带我去厨房",
        )

    def test_real_asr_alias(self):
        gate = create_gate()

        gate.on_wake(
            now=0.0,
        )

        result = gate.process(
            "拉可，你在吗？",
            now=1.0,
        )

        self.assertEqual(
            result.command,
            "你在吗",
        )

    def test_followup_no_wake(self):
        gate = create_gate()

        gate.on_wake(
            now=0.0,
        )

        gate.process(
            "你是谁",
            now=1.0,
        )

        result = gate.process(
            "你能做什么",
            now=5.0,
        )

        self.assertEqual(
            result.action,
            "command",
        )

        self.assertEqual(
            result.command,
            "你能做什么",
        )

    def test_timeout(self):
        gate = create_gate()

        gate.on_wake(
            now=0.0,
        )

        gate.process(
            "你是谁",
            now=1.0,
        )

        expired = (
            gate.expire_if_needed(
                now=14.0,
            )
        )

        self.assertTrue(
            expired
        )

        self.assertEqual(
            gate.state,
            gate.SLEEPING,
        )

    def test_chat_mode(self):
        gate = create_gate()

        gate.on_wake(
            now=0.0,
        )

        result = gate.process(
            "陪我聊聊天",
            now=1.0,
        )

        self.assertEqual(
            result.mode,
            gate.CHAT_MODE,
        )

        followup = gate.process(
            "我今天有点累",
            now=18.0,
        )

        self.assertEqual(
            followup.action,
            "command",
        )

    def test_explicit_sleep(self):
        gate = create_gate()

        gate.on_wake(
            now=0.0,
        )

        gate.process(
            "陪我聊聊天",
            now=1.0,
        )

        result = gate.process(
            "先这样吧",
            now=5.0,
        )

        self.assertEqual(
            result.action,
            "sleep",
        )

        self.assertEqual(
            gate.state,
            gate.SLEEPING,
        )


    def test_observed_wake_echo_variants(self):
        variants = [
            "Lucky。",
            "lucky。",
            "Luck。",
            "L克。",
            "拉uckK。",
            "拉ucky。",
            "拉。",
        ]

        for variant in variants:
            with self.subTest(
                variant=variant
            ):
                gate = create_gate()

                gate.on_wake(
                    now=0.0,
                )

                result = gate.process(
                    variant,
                    now=1.0,
                )

                self.assertEqual(
                    result.action,
                    "awake",
                )

                self.assertIsNone(
                    result.command
                )

    def test_observed_mixed_wake_command(self):
        gate = create_gate()

        gate.on_wake(
            now=0.0,
        )

        result = gate.process(
            "阿K,你在吗？",
            now=1.0,
        )

        self.assertEqual(
            result.command,
            "你在吗",
        )

    def test_real_command_starting_with_la(self):
        gate = create_gate()

        gate.on_wake(
            now=0.0,
        )

        result = gate.process(
            "拉开窗帘",
            now=1.0,
        )

        self.assertEqual(
            result.command,
            "拉开窗帘",
        )


    def test_active_repeated_wake_prefix(self):
        gate = create_gate()

        gate.on_wake(
            now=0.0,
        )

        gate.process(
            "你是谁",
            now=1.0,
        )

        result = gate.process(
            "Lucky,你会什么？",
            now=3.0,
        )

        self.assertEqual(
            result.action,
            "command",
        )

        self.assertEqual(
            result.command,
            "你会什么",
        )

    def test_active_wake_only_is_not_command(self):
        gate = create_gate()

        gate.on_wake(
            now=0.0,
        )

        gate.process(
            "你是谁",
            now=1.0,
        )

        result = gate.process(
            "Lucky。",
            now=3.0,
        )

        self.assertEqual(
            result.action,
            "awake",
        )

        self.assertIsNone(
            result.command
        )


if __name__ == "__main__":
    unittest.main()
