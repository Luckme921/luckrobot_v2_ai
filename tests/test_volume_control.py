import unittest

from edge.audio.volume import (
    parse_volume_command,
)


class VolumeCommandTest(
    unittest.TestCase
):
    def assert_action(
        self,
        text,
        action,
        percent=None,
    ):
        cmd = parse_volume_command(
            text
        )

        self.assertIsNotNone(cmd)
        self.assertEqual(
            cmd.action,
            action,
        )
        self.assertEqual(
            cmd.percent,
            percent,
        )

    def test_max_volume(self):
        self.assert_action(
            "最大音量",
            "max",
        )

    def test_volume_up(self):
        self.assert_action(
            "声音大一点",
            "up",
        )

    def test_volume_down(self):
        self.assert_action(
            "小声点",
            "down",
        )

    def test_volume_up_natural_order(self):
        self.assert_action(
            "音量调大一点",
            "up",
        )

    def test_volume_down_natural_order(self):
        self.assert_action(
            "音量调小一点",
            "down",
        )


    def test_short_volume_up(self):
        self.assert_action(
            "调大一点",
            "up",
        )

    def test_short_volume_down(self):
        self.assert_action(
            "调小一点",
            "down",
        )

    def test_unrelated_larger_request(self):
        self.assertIsNone(
            parse_volume_command(
                "字体调大一点"
            )
        )


    def test_current_volume(self):
        self.assert_action(
            "现在音量多少",
            "get",
        )

    def test_set_volume_number(self):
        self.assert_action(
            "音量调到30",
            "set",
            30,
        )

    def test_set_volume_percent(self):
        self.assert_action(
            "声音设为百分之65",
            "set",
            65,
        )


if __name__ == "__main__":
    unittest.main()
