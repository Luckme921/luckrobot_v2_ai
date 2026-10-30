import subprocess
import unittest
from unittest.mock import patch

from edge.audio.tts.phrase_cache import play_cached_reply


class CachedReplyPlaybackTests(unittest.TestCase):
    def test_observer_tracks_player_lifetime(self):
        events = []
        with patch("edge.audio.tts.phrase_cache.subprocess.run") as player:
            player.side_effect = lambda *args, **kwargs: events.append("played")
            play_cached_reply("greeting.wav", "speaker", events.append)
        self.assertEqual(events, [True, "played", False])
        player.assert_called_once_with(
            ["paplay", "--device=speaker", "greeting.wav"], check=True, timeout=15)

    def test_observer_clears_after_player_error(self):
        events = []
        with patch("edge.audio.tts.phrase_cache.subprocess.run",
                   side_effect=subprocess.CalledProcessError(1, "paplay")):
            with self.assertRaises(subprocess.CalledProcessError):
                play_cached_reply("greeting.wav", "speaker", events.append)
        self.assertEqual(events, [True, False])
