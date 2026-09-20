import unittest
from unittest.mock import Mock
from robot_tools.music import MusicTools, _autoplay_candidate

def song(sid, title="稻香", artist="周杰伦"):
    return dict(id=sid, title=title, artists=[artist], backend="http", url="https://example.com/"+sid)

class AutoPlayTests(unittest.TestCase):
    def test_title_only_never_autoplays(self):
        self.assertIsNone(_autoplay_candidate("稻香", [song("a",artist="翻唱歌手")],90,20))

    def test_all_candidates_compared_and_ranked(self):
        wanted=song("a")
        self.assertIs(_autoplay_candidate("周杰伦的稻香",[song("b","其他歌曲"),wanted],90,20),wanted)
        self.assertIsNone(_autoplay_candidate("周杰伦的稻香",[wanted,song("b","其他歌曲"),song("c")],90,20))

    def test_versions_require_selection_without_explicit_version(self):
        self.assertIsNone(_autoplay_candidate("周杰伦的稻香",[song("a"),song("b","稻香 (Live)")],90,20))
        self.assertIsNone(_autoplay_candidate("周杰伦的稻香",[song("a","稻香 (Demo)")],90,20))

    def test_switch_and_playback_gate(self):
        for enabled in (False,True):
            events=[];player=Mock(); player.play.side_effect=lambda url: events.append("play")
            music=MusicTools({"enabled":True,"provider":"http","http":{"search_url":"https://example.com","auto_play_enabled":enabled}},player=player,before_playback=lambda:events.append("ack_finished"))
            music.provider.search=Mock(return_value=[song("a")])
            result=music.search("周杰伦的稻香")
            if not enabled:
                self.assertEqual(result["status"],"needs_selection")
                self.assertEqual(events,[])
                music.select("第一首")
            else: self.assertTrue(result["playing"])
            self.assertEqual(events,["ack_finished","play"])

    def test_gate_failure_prevents_playback(self):
        player=Mock();music=MusicTools({"enabled":True},player=player,before_playback=Mock(side_effect=RuntimeError()))
        music.pending=[song("a")];music.deadline=music.clock()+120
        with self.assertRaises(RuntimeError):music.select("第一首")
        player.play.assert_not_called()

    def test_invalid_ranges_disable_autoplay(self):
        for threshold,gap in [(0,20),(101,20),(90,-1),(90,101),(float("nan"),20)]:
            self.assertIsNone(_autoplay_candidate("周杰伦的稻香",[song("a")],threshold,gap))
