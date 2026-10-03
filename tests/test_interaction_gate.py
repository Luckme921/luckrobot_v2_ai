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
            "马蹄",
            "拉ucky",
            "老uck克",
            "老克",
            "拉客",
            "那克",
            "拉y",
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
        post_kws_transcript_aliases=[
            "拉uck",
            "拉圾",
            "垃圾",
            "马蹄",
        ],
    )


class InteractionGateTest(
    unittest.TestCase
):
    def test_speech_activity_defers_timeout_until_segment_is_processed(self):
        gate = create_gate()
        gate.on_wake(0.0)
        gate.note_speech_activity(7.9)
        self.assertFalse(gate.expire_if_needed(9.0))
        result = gate.process("帮我看看天气", now=18.0, defer_timeout=True)
        self.assertEqual(result.action, "command")
        self.assertEqual(gate.state, gate.ACTIVE)

    def test_repeated_wake_echo_does_not_start_model_turn(self):
        gate = create_gate()
        gate.on_wake(0.0)
        result = gate.process("拉铁拉铁", now=1.0)
        self.assertEqual(result.action, "ignore")
        self.assertEqual(gate.state, gate.AWAKE_WAIT_COMMAND)

    def test_pre_wake_speech_is_optional(self):
        gate = create_gate()
        gate.on_wake(0.0)
        result = gate.process("今天天气怎么样，Lucky，告诉我气温", now=1.0)
        self.assertEqual(result.command, "告诉我气温")
        gate = create_gate()
        gate.include_pre_wake_speech = True
        gate.on_wake(0.0)
        result = gate.process("今天天气怎么样，Lucky，告诉我气温", now=1.0)
        self.assertEqual(result.command, "今天天气怎么样，Lucky，告诉我气温")

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
            result.action,
            "awake",
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
            "马蹄。",
            "拉圾。",
            "拉y。",
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

    def test_wake_alias_with_command_is_normalized_only_for_model(self):
        gate = create_gate()
        gate.on_wake(now=0.0)

        result = gate.process("拉圾，帮我看看天气", now=1.0)

        self.assertEqual(result.action, "command")
        self.assertEqual(result.command, "帮我看看天气")
        self.assertTrue(result.wake_detected)
        self.assertEqual(result.command_for_model, "Lucky，帮我看看天气")

    def test_ambiguous_post_kws_alias_remains_normal_during_active_turn(self):
        gate = create_gate()
        gate.on_wake(now=0.0)
        gate.process("你是谁", now=1.0)

        result = gate.process("垃圾分类怎么做", now=2.0)

        self.assertEqual(result.command, "垃圾分类怎么做")
        self.assertFalse(result.wake_detected)

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
            result.action,
            "awake",
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

    def test_short_fragments_after_wake_never_reach_model(self):
        gate = create_gate()
        gate.on_wake(now=0.0)
        echo = gate.process("拉y。", now=1.0)
        self.assertEqual(echo.action, "awake")
        self.assertIsNone(echo.command_for_model)
        fragment = gate.process("体。", now=2.0)
        self.assertEqual(fragment.action, "ignore")
        self.assertEqual(gate.state, gate.AWAKE_WAIT_COMMAND)
        command = gate.process("帮我查天气", now=3.0)
        self.assertEqual(command.action, "command")
        self.assertEqual(command.command_for_model, "帮我查天气")


if __name__ == "__main__":
    unittest.main()
