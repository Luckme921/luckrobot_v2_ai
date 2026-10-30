import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from robot_tools import music_aliases
from robot_tools.music import _qq_candidate_matches_query, explicit_candidate
from robot_tools.catalog import MUSIC_ALIAS_SCHEMA, TOOL_SCHEMAS
from robot_tools.registry import validate


class MusicAliasTests(unittest.TestCase):
    def test_model_tool_contract_is_registered(self):
        self.assertIn("music_alias_add", [item["function"]["name"]
                                          for item in TOOL_SCHEMAS])
        validate({"kind": "artists", "canonical": "邓紫棋",
                  "alias": "G.E.M.邓紫棋", "evidence": "QQ 页面写明 G.E.M.邓紫棋"},
                 MUSIC_ALIAS_SCHEMA)

    def test_curated_artist_and_title_aliases(self):
        self.assertTrue(music_aliases.equivalent("artists", "邓紫棋", "G.E.M.邓紫棋"))
        self.assertTrue(music_aliases.equivalent("artists", "乃万", "乃万NINEONE"))
        song = {"title": "安和桥 (Live)", "artists": ["宋冬野"]}
        self.assertTrue(_qq_candidate_matches_query("安河桥", song))
        self.assertIsNotNone(explicit_candidate("宋冬野 安河桥", [song]))

    def test_model_tool_writes_only_private_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            learned = Path(directory) / "aliases.json"
            with patch.object(music_aliases, "LEARNED", learned):
                saved = music_aliases.add_alias("artists", "测试歌手", "测试艺名",
                                                "用户明确说测试艺名就是测试歌手")
                self.assertEqual(saved["status"], "saved")
                self.assertTrue(music_aliases.equivalent("artists", "测试歌手", "测试艺名"))
                self.assertEqual(music_aliases.add_alias("artists", "另一位", "测试艺名",
                                                         "联网结果明确说这是另一位")["status"],
                                 "rejected")
                self.assertEqual(music_aliases.add_alias("artists", "人", "错",
                                                         "证据不足")["status"], "rejected")
                self.assertEqual(music_aliases.add_alias("songs", "测试歌曲", "测试别称",
                                                         "网页写了这是同一首歌")["status"],
                                 "rejected")
