from __future__ import annotations

from functools import wraps

import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from selenium.webdriver.common.by import By


PROFILE_CREATE_URL = (
    "https://y.qq.com/n/ryqq_v2/profile/create"
)

PLAYLIST_URL = (
    "https://y.qq.com/n/ryqq_v2/playlist/{playlist_id}"
)

MUSIC_API_URL = (
    "https://u.y.qq.com/cgi-bin/musicu.fcg"
)


def _normalize(text: str) -> str:
    return re.sub(
        r"[^0-9a-zA-Z\u4e00-\u9fff]+",
        "",
        str(text).casefold(),
    )


@dataclass(frozen=True)
class PersonalSong:
    mid: str
    title: str
    artists: tuple[str, ...]
    album: str
    playlist_id: str
    playlist_name: str
    score: float = 0.0

    @property
    def artist_text(self) -> str:
        return " /".join(self.artists)


def _library_driver_locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        # QQMusicController.play/pause/etc use
        # this exact same RLock. Selenium is
        # therefore never driven concurrently.
        with self.controller._driver_lock:
            driver = (
                self.controller
                ._require_driver()
            )

            previous_handle = None

            try:
                previous_handle = (
                    driver.current_window_handle
                )
            except Exception:
                pass

            handles = list(
                driver.window_handles
            )

            library_handle = getattr(
                self,
                "_library_handle",
                None,
            )

            # Keep library crawling away from both
            # the normal search tab and /player.
            if library_handle not in handles:
                driver.switch_to.new_window(
                    "tab"
                )

                library_handle = (
                    driver.current_window_handle
                )

                self._library_handle = (
                    library_handle
                )

                print(
                    "[LIBRARY] WINDOW_READY "
                    f"handle={library_handle}",
                    flush=True,
                )

            else:
                driver.switch_to.window(
                    library_handle
                )

            try:
                return method(
                    self,
                    *args,
                    **kwargs,
                )

            finally:
                # Always leave Selenium on the tab
                # that was active before this sync
                # transaction.
                try:
                    handles = list(
                        driver.window_handles
                    )

                    if (
                        previous_handle
                        in handles
                    ):
                        driver.switch_to.window(
                            previous_handle
                        )

                    else:
                        search_handle = getattr(
                            self.controller,
                            "_search_handle",
                            None,
                        )

                        if (
                            search_handle
                            in handles
                        ):
                            driver.switch_to.window(
                                search_handle
                            )

                except Exception as exc:
                    print(
                        "[LIBRARY] "
                        "WINDOW_RESTORE_ERROR "
                        f"{type(exc).__name__}: "
                        f"{exc}",
                        flush=True,
                    )

    return wrapped


class QQMusicPersonalLibrary:
    # QQ Music exposes the old QZone playlist
    # differently from normal created playlists.
    # Its playlist id was discovered from the
    # logged-in owner's profile page.
    LEGACY_PLAYLIST_NAMES = {
        "205": "QZone背景音乐",
    }

    """
    Dynamic personal QQ Music library.

    Cache lives under private/ so the robot can:
      - start from the previous snapshot immediately;
      - refresh from QQ Music in the background;
      - pick up songs added from the phone later.
    """

    CACHE_VERSION = 1

    # These are semantic meanings supplied by the
    # owner. Playlist names still come from QQ Music;
    # aliases only determine which playlist a natural
    # language request should prefer.
    PLAYLIST_ALIASES = {
        "QZone背景音乐": (
            "qzone",
            "qq空间",
            "空间背景音乐",
            "空间音乐",
            "qq空间背景",
        ),
        "背景": (
            "背景",
            "背景歌单",
            "背景音乐",
            "来点dj",
            "放点dj",
            "来首dj",
            "放首dj",
            "dj音乐",
            "dj舞曲",
            "电音",
            "电子音乐",
            "蹦迪",
            "摇滚",
            "摇滚乐",
            "高燃",
            "燃一点",
            "燃起来",
            "热血",
            "激情",
            "带劲",
            "劲爆",
            "炸场",
            "引爆全场",
            "嗨一点",
            "气氛拉满",
            "战歌",
            "积极向上",
            "振奋",
            "有力量",
        ),
        "给你的愉快与轻松": (
            "轻松",
            "愉快",
            "轻松愉快",
            "小清新",
            "清新",
            "放松",
            "舒服",
            "治愈",
            "阳光",
            "欢快",
            "开心",
            "悠闲",
            "惬意",
            "心情好",
            "愉悦",
        ),
        "是你的抒情歌曲": (
            "抒情",
            "抒情歌曲",
            "慢歌",
            "温柔",
            "安静",
            "深情",
            "情歌",
            "伤感",
            "柔和",
            "舒缓",
            "夜晚听",
            "睡前听",
            "静一点",
        ),
        "民谣": (
            "民谣",
            "民谣歌曲",
            "木吉他",
        ),
        "许嵩": (
            "许嵩",
            "vae",
        ),
        "周本轮": (
            "周本轮",
            "周杰伦",
            "周董",
            "杰伦",
        ),
        "跑步": (
            "跑步",
            "运动",
            "健身",
            "训练",
            "运动音乐",
            "跑步音乐",
        ),
        "搞笑背景": (
            "搞笑",
            "整活",
            "搞怪",
            "沙雕",
            "鬼畜",
            "哈基米",
            "搞笑背景",
        ),
        "我喜欢": (
            "我喜欢",
            "喜欢的歌",
            "我收藏的歌",
            "收藏的歌",
            "我的歌",
        ),
    }

    VERSION_MARKERS = (
        "live",
        "现场",
        "dj",
        "remix",
        "翻唱",
        "cover",
        "伴奏",
        "纯音乐",
        "spedup",
        "加速版",
    )

    def __init__(
        self,
        controller: Any,
        *,
        cache_path: str | Path = (
            "private/qqmusic-library.json"
        ),
        page_size: int = 100,
    ) -> None:
        self.controller = controller
        self.cache_path = Path(cache_path)
        self.page_size = int(page_size)
        self.data: dict[str, Any] = {
            "version": self.CACHE_VERSION,
            "refreshed_at": None,
            "playlists": {},
        }

        self.load_cache()

    def load_cache(self) -> bool:
        if not self.cache_path.exists():
            return False

        try:
            raw = json.loads(
                self.cache_path.read_text(
                    encoding="utf-8",
                )
            )

            if not isinstance(raw, dict):
                return False

            if (
                raw.get("version")
                != self.CACHE_VERSION
            ):
                return False

            self.data = raw
            return True

        except Exception:
            return False

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        tmp = self.cache_path.with_suffix(
            ".json.tmp"
        )

        tmp.write_text(
            json.dumps(
                self.data,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        tmp.replace(self.cache_path)

    def _driver(self):
        return self.controller._require_driver()

    def _navigate_with_retry(
        self,
        url: str,
        *,
        attempts: int = 4,
    ) -> None:
        d = self._driver()
        last_error = None

        for attempt in range(
            1,
            attempts + 1,
        ):
            try:
                d.get(url)
                return

            except Exception as exc:
                last_error = exc

                print(
                    "[LIBRARY] NAV_RETRY "
                    f"attempt={attempt}/"
                    f"{attempts} "
                    f"url={url!r} "
                    f"error="
                    f"{type(exc).__name__}: "
                    f"{exc}",
                    flush=True,
                )

                if attempt < attempts:
                    time.sleep(
                        min(
                            2.0 * attempt,
                            6.0,
                        )
                    )

        raise RuntimeError(
            "QQ Music navigation failed "
            f"after {attempts} attempts: "
            f"{url}: {last_error}"
        )

    @_library_driver_locked
    def discover_playlist_ids(
        self,
    ) -> list[str]:
        d = self._driver()

        self._navigate_with_retry(
            PROFILE_CREATE_URL
        )

        deadline = time.monotonic() + 15.0
        ids: list[str] = []

        while time.monotonic() < deadline:
            found: list[str] = []

            for element in d.find_elements(
                By.CSS_SELECTOR,
                "a[href*='/playlist/']",
            ):
                href = (
                    element.get_attribute("href")
                    or ""
                )

                match = re.search(
                    r"/playlist/(\d+)",
                    href,
                )

                if not match:
                    continue

                pid = match.group(1)

                if pid not in found:
                    found.append(pid)

            if found:
                ids = found
                break

            time.sleep(0.2)

        if not ids:
            raise RuntimeError(
                "No personal QQ Music playlists "
                "were discovered"
            )

        return ids

    @_library_driver_locked
    def _playlist_detail(
        self,
        playlist_id: str,
    ) -> dict[str, Any]:
        d = self._driver()

        self._navigate_with_retry(
            PLAYLIST_URL.format(
                playlist_id=playlist_id,
            )
        )

        deadline = time.monotonic() + 15.0

        while time.monotonic() < deadline:
            detail = d.execute_script(
                """
                const root =
                    window.__INITIAL_DATA__;

                if (!root || !root.detail) {
                    return null;
                }

                return root.detail;
                """
            )

            if (
                isinstance(detail, dict)
                and str(detail.get("id"))
                == str(playlist_id)
            ):
                return detail

            time.sleep(0.1)

        raise RuntimeError(
            "QQ Music playlist detail "
            f"did not load: {playlist_id}"
        )

    @_library_driver_locked
    def _fetch_page(
        self,
        playlist_id: str,
        begin: int,
    ) -> list[dict[str, Any]]:
        d = self._driver()

        d.set_script_timeout(30)

        result = d.execute_async_script(
            """
            const id = arguments[0];
            const begin = arguments[1];
            const num = arguments[2];
            const done =
                arguments[arguments.length - 1];

            const payload = {
                comm: {
                    ct: 24,
                    cv: 0
                },
                req_1: {
                    module:
                        "music.srfDissInfo.aiDissInfo",
                    method:
                        "uniform_get_Dissinfo",
                    param: {
                        disstid: Number(id),
                        song_begin: begin,
                        song_num: num,
                        tag: 1,
                        userinfo: 0,
                        orderlist: 1
                    }
                }
            };

            fetch(
                arguments[3],
                {
                    method: "POST",
                    credentials: "include",
                    headers: {
                        "Content-Type":
                            "application/json"
                    },
                    body: JSON.stringify(payload)
                }
            )
            .then(r => r.json())
            .then(data => done({
                ok: true,
                data: data
            }))
            .catch(err => done({
                ok: false,
                error: String(err)
            }));
            """,
            str(playlist_id),
            int(begin),
            self.page_size,
            MUSIC_API_URL,
        )

        if not result.get("ok"):
            raise RuntimeError(
                "QQ Music playlist API error: "
                f"{result.get('error')}"
            )

        req = (
            result.get("data", {})
            .get("req_1", {})
        )

        if req.get("code") not in (
            None,
            0,
        ):
            raise RuntimeError(
                "QQ Music playlist API "
                f"code={req.get('code')}"
            )

        body = req.get("data") or {}

        songs = (
            body.get("songlist")
            or body.get("songInfoList")
            or body.get("songList")
            or []
        )

        if not isinstance(songs, list):
            return []

        return songs

    @staticmethod
    def _song_record(
        raw: dict[str, Any],
    ) -> dict[str, Any] | None:
        mid = str(
            raw.get("mid")
            or raw.get("songmid")
            or ""
        ).strip()

        title = str(
            raw.get("name")
            or raw.get("title")
            or ""
        ).strip()

        if not mid or not title:
            return None

        artists = []

        for singer in (
            raw.get("singer")
            or []
        ):
            if not isinstance(
                singer,
                dict,
            ):
                continue

            name = str(
                singer.get("name")
                or ""
            ).strip()

            if name:
                artists.append(name)

        album_raw = raw.get("album") or {}

        if isinstance(
            album_raw,
            dict,
        ):
            album = str(
                album_raw.get("name")
                or album_raw.get("title")
                or ""
            ).strip()
        else:
            album = ""

        return {
            "mid": mid,
            "title": title,
            "artists": artists,
            "album": album,
        }

    def refresh_all(
        self,
    ) -> dict[str, Any]:
        ids = self.discover_playlist_ids()

        playlists: dict[str, Any] = {}

        print(
            "[LIBRARY] DISCOVERED "
            f"playlists={len(ids)}",
            flush=True,
        )

        for index, pid in enumerate(
            ids,
            start=1,
        ):
            cached = (
                self.data
                .get("playlists", {})
                .get(pid, {})
            )

            # Existing playlists do not need a page
            # navigation just to rediscover their name.
            #
            # This is important because playlist detail
            # navigation holds the shared Selenium lock
            # and can delay an interactive play command.
            #
            # Set total=0 deliberately: refresh pages
            # until QQ Music returns a short page, so
            # songs newly added from the phone are still
            # discovered even if the cached song count
            # is old.
            if cached:
                name = str(
                    cached.get("name")
                    or self.LEGACY_PLAYLIST_NAMES.get(
                        str(pid)
                    )
                    or pid
                ).strip()

                total = 0

                print(
                    "[LIBRARY] META_CACHE "
                    f"id={pid} "
                    f"name={name!r}",
                    flush=True,
                )

            else:
                try:
                    detail = self._playlist_detail(
                        pid
                    )

                    name = str(
                        detail.get("title")
                        or pid
                    ).strip()

                    total = int(
                        detail.get("songnum")
                        or 0
                    )

                except RuntimeError as exc:
                    name = str(
                        self.LEGACY_PLAYLIST_NAMES.get(
                            str(pid)
                        )
                        or pid
                    ).strip()

                    total = 0

                    print(
                        "[LIBRARY] DETAIL_FALLBACK "
                        f"id={pid} "
                        f"name={name!r} "
                        f"error={exc}",
                        flush=True,
                    )

            print(
                "[LIBRARY] SYNC "
                f"{index}/{len(ids)} "
                f"name={name!r} "
                f"id={pid} "
                f"expected={total}",
                flush=True,
            )

            unique: dict[
                str,
                dict[str, Any],
            ] = {}

            begin = 0

            while True:
                page = self._fetch_page(
                    pid,
                    begin,
                )

                if not page:
                    break

                for raw in page:
                    record = (
                        self._song_record(raw)
                    )

                    if record is None:
                        continue

                    unique[
                        record["mid"]
                    ] = record

                begin += len(page)

                print(
                    "[LIBRARY] PAGE "
                    f"name={name!r} "
                    f"loaded={len(unique)}",
                    flush=True,
                )

                if len(page) < self.page_size:
                    break

                if (
                    total > 0
                    and begin >= total
                ):
                    break

            if total <= 0:
                total = len(unique)

            playlists[pid] = {
                "id": pid,
                "name": name,
                "songnum": total,
                "songs": list(
                    unique.values()
                ),
            }

            print(
                "[LIBRARY] SYNC_OK "
                f"name={name!r} "
                f"songs={len(unique)}",
                flush=True,
            )

        self.data = {
            "version": self.CACHE_VERSION,
            "refreshed_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "playlists": playlists,
        }

        self._save_cache()

        total_songs = sum(
            len(
                item.get(
                    "songs",
                    [],
                )
            )
            for item in playlists.values()
        )

        print(
            "[LIBRARY] REFRESH_OK "
            f"playlists={len(playlists)} "
            f"songs={total_songs}",
            flush=True,
        )

        return self.data

    def playlist_names(
        self,
    ) -> list[str]:
        return [
            str(item.get("name") or "")
            for item in (
                self.data
                .get("playlists", {})
                .values()
            )
            if item.get("name")
        ]

    def playlist_for_query(
        self,
        query: str,
    ) -> str | None:
        q = _normalize(query)

        if not q:
            return None

        available = set(
            self.playlist_names()
        )

        matches: list[
            tuple[int, str]
        ] = []

        for playlist, aliases in (
            self.PLAYLIST_ALIASES.items()
        ):
            if playlist not in available:
                continue

            for alias in aliases:
                normalized_alias = (
                    _normalize(alias)
                )

                if (
                    normalized_alias
                    and normalized_alias in q
                ):
                    matches.append(
                        (
                            len(
                                normalized_alias
                            ),
                            playlist,
                        )
                    )

        if not matches:
            return None

        # More specific expressions win.
        # e.g. "QQ空间背景音乐" beats
        # generic "背景音乐".
        matches.sort(
            key=lambda x: x[0],
            reverse=True,
        )

        return matches[0][1]

    @classmethod
    def is_random_request(
        cls,
        text: str,
    ) -> bool:
        q = _normalize(text)

        # GENERIC_RANDOM_MUSIC_COMMANDS
        #
        # These are complete generic play requests,
        # not explicit titles/artists. Match them
        # exactly so something such as
        # "放首廖野天的空心" never becomes random.
        if q in {
            _normalize("放歌"),
            _normalize("放首歌"),
            _normalize("放一首歌"),
            _normalize("放首歌曲"),
            _normalize("放一首歌曲"),
            _normalize("播放歌曲"),
            _normalize("来首歌"),
            _normalize("来一首歌"),
            _normalize("来首歌曲"),
            _normalize("来一首歌曲"),
            _normalize("给我放首歌"),
            _normalize("给我放一首歌"),
            _normalize("给我放首歌曲"),
            _normalize("给我放一首歌曲"),
            _normalize("放歌放歌"),
        }:
            return True


        if not q:
            return False

        exact = {
            "放一首",
            "来一首",
            "来首歌",
            "放首歌",
            "来点歌",
            "放点歌",
            "不知道听什么",
            "不知道听啥",
        }

        if q in exact:
            return True

        if (
            (
                "随便" in q
                or "随机" in q
            )
            and (
                "歌" in q
                or "一首" in q
            )
        ):
            return True

        return False

    def best_match(
        self,
        query: str,
    ) -> PersonalSong | None:
        results = self.search(
            query,
            limit=3,
        )

        if not results:
            return None

        top = results[0]

        # Exact / strong title match.
        if top.score >= 60.0:
            return top

        # Allow an ASR-damaged title when
        # the requested artist is explicit.
        q = _normalize(query)

        # Ignore common conversational particles
        # at the end of a generic music request.
        for suffix in (
            "一下吧",
            "一下",
            "吧",
            "呗",
            "呀",
            "啊",
        ):
            normalized_suffix = (
                _normalize(suffix)
            )

            if (
                normalized_suffix
                and q.endswith(
                    normalized_suffix
                )
            ):
                q = q[
                    :-len(
                        normalized_suffix
                    )
                ]
                break

        artist_matched = any(
            _normalize(artist) in q
            for artist in top.artists
            if _normalize(artist)
        )

        if (
            artist_matched
            and top.score >= 30.0
        ):
            return top

        return None

    def _iter_songs(
        self,
        playlist_name: str | None = None,
    ):
        seen: set[str] = set()

        for playlist in (
            self.data
            .get("playlists", {})
            .values()
        ):
            name = str(
                playlist.get("name")
                or ""
            )

            if (
                playlist_name is not None
                and name != playlist_name
            ):
                continue

            for song in (
                playlist.get("songs")
                or []
            ):
                mid = str(
                    song.get("mid")
                    or ""
                )

                if not mid or mid in seen:
                    continue

                seen.add(mid)

                yield PersonalSong(
                    mid=mid,
                    title=str(
                        song.get("title")
                        or ""
                    ),
                    artists=tuple(
                        str(x)
                        for x in (
                            song.get("artists")
                            or []
                        )
                        if str(x)
                    ),
                    album=str(
                        song.get("album")
                        or ""
                    ),
                    playlist_id=str(
                        playlist.get("id")
                        or ""
                    ),
                    playlist_name=name,
                )

    @classmethod
    def _score_song(
        cls,
        query: str,
        song: PersonalSong,
    ) -> float:
        q = _normalize(query)
        title = _normalize(
            song.title
        )

        artists = [
            _normalize(x)
            for x in song.artists
        ]

        if not q or not title:
            return 0.0

        score = 0.0

        if q == title:
            score += 100.0

        elif title in q:
            score += 60.0

        elif q in title:
            score += 45.0

        score += (
            SequenceMatcher(
                None,
                q,
                title,
            ).ratio()
            * 20.0
        )

        for artist in artists:
            if (
                artist
                and artist in q
            ):
                score += 25.0

        title_lower = song.title.casefold()
        query_lower = str(
            query
        ).casefold()

        for marker in (
            cls.VERSION_MARKERS
        ):
            if (
                marker in title_lower
                and marker not in query_lower
            ):
                score -= 7.0

        return score

    def search(
        self,
        query: str,
        *,
        playlist_name: str | None = None,
        limit: int = 5,
    ) -> list[PersonalSong]:
        ranked = []

        for song in self._iter_songs(
            playlist_name
        ):
            score = self._score_song(
                query,
                song,
            )

            if score <= 0:
                continue

            ranked.append(
                PersonalSong(
                    mid=song.mid,
                    title=song.title,
                    artists=song.artists,
                    album=song.album,
                    playlist_id=(
                        song.playlist_id
                    ),
                    playlist_name=(
                        song.playlist_name
                    ),
                    score=score,
                )
            )

        ranked.sort(
            key=lambda x: x.score,
            reverse=True,
        )

        return ranked[:limit]

    def random_song(
        self,
        playlist_name: str | None = None,
    ) -> PersonalSong | None:
        songs = list(
            self._iter_songs(
                playlist_name
            )
        )

        if not songs:
            return None

        return random.choice(songs)
