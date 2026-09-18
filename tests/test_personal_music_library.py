import tempfile
import unittest
from pathlib import Path

from edge.music.personal_library import (
    QQMusicPersonalLibrary,
)


class FakeController:
    pass


class PersonalMusicLibraryTest(
    unittest.TestCase
):
    def make_library(self):
        tmp = tempfile.TemporaryDirectory()

        self.addCleanup(
            tmp.cleanup
        )

        lib = QQMusicPersonalLibrary(
            FakeController(),
            cache_path=(
                Path(tmp.name)
                / "library.json"
            ),
        )

        names = [
            "QZone背景音乐",
            "我喜欢",
            "民谣",
            "许嵩",
            "搞笑背景",
            "周本轮",
            "背景",
            "给你的愉快与轻松",
            "跑步",
            "是你的抒情歌曲",
        ]

        lib.data = {
            "version": 1,
            "refreshed_at": None,
            "playlists": {
                str(i): {
                    "id": str(i),
                    "name": name,
                    "songs": [],
                }
                for i, name
                in enumerate(names)
            },
        }

        return lib

    def test_lyrical_request(
        self,
    ):
        lib = self.make_library()

        self.assertEqual(
            lib.playlist_for_query(
                "给我一点抒情的歌曲"
            ),
            "是你的抒情歌曲",
        )

    def test_rock_maps_to_background(
        self,
    ):
        lib = self.make_library()

        self.assertEqual(
            lib.playlist_for_query(
                "给我来点摇滚的"
            ),
            "背景",
        )

    def test_background_music(
        self,
    ):
        lib = self.make_library()

        self.assertEqual(
            lib.playlist_for_query(
                "播放点背景音乐"
            ),
            "背景",
        )

    def test_qzone_is_more_specific(
        self,
    ):
        lib = self.make_library()

        self.assertEqual(
            lib.playlist_for_query(
                "放点QQ空间背景音乐"
            ),
            "QZone背景音乐",
        )

    def test_relaxing_music(
        self,
    ):
        lib = self.make_library()

        self.assertEqual(
            lib.playlist_for_query(
                "来点小清新的放松一下"
            ),
            "给你的愉快与轻松",
        )

    def test_jay_chou(
        self,
    ):
        lib = self.make_library()

        self.assertEqual(
            lib.playlist_for_query(
                "放点周董的歌"
            ),
            "周本轮",
        )


    def test_dj_maps_to_background(
        self,
    ):
        lib = self.make_library()

        self.assertEqual(
            lib.playlist_for_query(
                "来点DJ舞曲引爆全场"
            ),
            "背景",
        )


    def test_generic_play_song_is_random(self):
        lib = self.make_library()

        self.assertTrue(
            lib.is_random_request(
                "放首歌曲"
            )
        )

    def test_repeated_play_song_is_random(self):
        lib = self.make_library()

        self.assertTrue(
            lib.is_random_request(
                "放歌放歌"
            )
        )

    def test_explicit_song_is_not_random(self):
        lib = self.make_library()

        self.assertFalse(
            lib.is_random_request(
                "放首廖野天的空心"
            )
        )


if __name__ == "__main__":
    unittest.main()
