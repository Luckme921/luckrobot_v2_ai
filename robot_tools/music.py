"""Search -> pending candidates -> explicit choice -> trusted provider playback."""
import json
import os
import re
import shutil
import signal
import subprocess
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

def result(message, *, ok=True, status="success", executed=False, playing=False, **data):
    return dict(ok=ok, status=status, executed=executed, playing=playing, message=message, **data)

class HttpMusicProvider:
    """Adapter contract: GET search_url?q=...&limit=3 -> {"songs":[...]}."""
    def __init__(self, config):
        self.url = str(config.get("search_url", "")).strip()
        self.token_env = str(config.get("token_env", "MUSIC_API_TOKEN"))
        self.timeout = min(30.0, max(1.0, float(config.get("timeout_seconds", 10))))

    def search(self, query):
        if urlsplit(self.url).scheme not in {"http", "https"}:
            raise ValueError("Configure music.http.search_url first")
        headers = {"Accept": "application/json"}
        token = os.getenv(self.token_env, "")
        if token:
            headers["Authorization"] = "Bearer " + token
        joiner = "&" if "?" in self.url else "?"
        req = Request(self.url + joiner + urlencode({"q": query, "limit": 3}), headers=headers)
        with urlopen(req, timeout=self.timeout) as response:
            body = response.read(1_000_001)
        if len(body) > 1_000_000:
            raise ValueError("Music response too large")
        songs = json.loads(body).get("songs")
        if not isinstance(songs, list):
            raise ValueError("Music API must return a songs list")
        clean = []
        seen = set()
        for song in songs[:50]:
            if not isinstance(song, dict):
                continue
            sid, title, url = (str(song.get(k, "")).strip() for k in ("id", "title", "url"))
            artists = song.get("artists", [])
            if not sid or sid in seen or not title or urlsplit(url).scheme not in {"http", "https"}:
                continue
            if not isinstance(artists, list) or not all(isinstance(a, str) for a in artists):
                continue
            expires = song.get("expires_at")
            if expires is not None and (type(expires) not in (int, float) or expires <= time.time()):
                continue
            clean.append(dict(id=sid[:200], title=title[:120], artists=artists[:5],
                              url=url, expires_at=expires, backend="http"))
            seen.add(sid)
            if len(clean) == 3:
                break
        return clean

class TangMusicProvider:
    """Adapter for the QQ JSON endpoint extracted from wangye.html."""
    def __init__(self, config):
        self.url = str(config.get("search_url") or "https://tang.api.s01s.cn/music_open_api.php")
        self.timeout = min(30., max(1., float(config.get("timeout_seconds", 10))))

    def _request(self, parameters):
        request = Request(self.url + ("&" if "?" in self.url else "?") + urlencode(parameters),
                          headers={"Accept": "application/json"})
        with urlopen(request, timeout=self.timeout) as response:
            body = response.read(1_000_001)
        if len(body) > 1_000_000:
            raise ValueError("Music response too large")
        return json.loads(body)

    def search(self, query):
        data = self._request({"msg": query, "type": "json"})
        data = data.get("data") if isinstance(data, dict) else data
        if not isinstance(data, list):
            raise ValueError("Invalid music search response")
        songs, seen = [], set()
        for item in data[:50]:
            if not isinstance(item, dict):
                continue
            mid, title = item.get("song_mid"), item.get("song_title")
            if not isinstance(mid, str) or not mid or mid in seen or not isinstance(title, str) or not title:
                continue
            artist = item.get("singer_name")
            songs.append(dict(id=mid, title=title[:120], artists=[artist] if isinstance(artist, str) else [],
                              query=query, backend="http", resolver="tang"))
            seen.add(mid)
            if len(songs) == 3:
                break
        return songs

    def resolve(self, song):
        data = self._request({"msg": song["query"], "type": "json", "mid": song["id"]})
        if not isinstance(data, dict) or data.get("song_mid") != song["id"]:
            raise ValueError("Music detail does not match selected song")
        # Prefer normal vocal audio; accompaniment is never selected implicitly.
        for key in ("song_play_url_standard", "song_play_url_hq", "song_play_url", "song_play_url_sq", "song_play_url_pq", "song_play_url_fq"):
            url = data.get(key)
            if isinstance(url, str) and urlsplit(url).scheme in {"http", "https"} and urlsplit(url).hostname:
                return url
        raise ValueError("Selected song has no playable URL")


class NeteaseMusicProvider(TangMusicProvider):
    """Search and resolve using the two endpoints from wangye.html."""
    def __init__(self, config):
        super().__init__(config)
        self.url = "https://api.vkeys.cn/v2/music/netease"

    def search(self, query):
        data = self._request({"word": query, "page": 1, "num": 3})
        if not isinstance(data, dict) or data.get("code") != 200 or not isinstance(data.get("data"), list):
            raise ValueError("Invalid Netease search response")
        songs, seen = [], set()
        for item in data["data"]:
            if not isinstance(item, dict): continue
            sid, title = str(item.get("id", "")), item.get("song")
            if not sid.isdigit() or sid in seen or not isinstance(title, str) or not title: continue
            seen.add(sid)
            artist = item.get("singer")
            songs.append(dict(id=sid, title=title[:120], artists=[artist] if isinstance(artist, str) else [],
                              backend="http", resolver="netease", query=query))
            if len(songs) == 3: break
        return songs

    def resolve(self, song):
        if not str(song["id"]).isdigit(): raise ValueError("Invalid song ID")
        helper = TangMusicProvider({"search_url": "https://api.qijieya.cn/meting/", "timeout_seconds": self.timeout})
        data = helper._request({"type": "song", "id": song["id"]})
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise ValueError("Invalid Netease detail response")
        detail = data[0]
        if detail.get("name") != song["title"]:
            raise ValueError("Music detail title changed")
        url = detail.get("url")
        if not isinstance(url, str) or urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).hostname:
            raise ValueError("Missing audio URL")
        return url


class FallbackMusicProvider:
    """Fallback only during search; never replace an explicitly selected song."""
    def __init__(self, config):
        self.providers = {"tang": TangMusicProvider(config), "netease": NeteaseMusicProvider(config)}
        self.url = self.providers["tang"].url

    def search(self, query):
        errors = []
        for name, provider in self.providers.items():
            try:
                songs = provider.search(query)
                if songs:
                    print(f"[MUSIC] SEARCH_SOURCE provider={name} candidates={len(songs)}", flush=True)
                    return songs
            except (OSError, ValueError, TypeError, KeyError) as exc:
                errors.append(type(exc).__name__)
                print(f"[MUSIC] SEARCH_SOURCE_FAILED provider={name} error={type(exc).__name__}", flush=True)
        if errors: raise RuntimeError("Music search services unavailable")
        return []

    def resolve(self, song):
        return self.providers[song["resolver"]].resolve(song)


class DirectAudioPlayer:
    """Use installed GStreamer; never accept a user/model-supplied URI."""
    def __init__(self, sink):
        self.sink = sink
        self.process = None
        self.paused = False

    @property
    def playing(self):
        return self.process is not None and self.process.poll() is None and not self.paused

    def play(self, url):
        if urlsplit(url).scheme not in {"http", "https"}:
            raise ValueError("Only provider HTTP audio addresses are supported")
        binary = shutil.which("gst-launch-1.0")
        if not binary:
            raise RuntimeError("GStreamer player is unavailable")
        sink = self.sink()
        self.stop()
        self.process = subprocess.Popen(
            [binary, "-q", "playbin", "uri=" + url, "audio-sink=pulsesink device=" + sink],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.process.wait(timeout=0.3)
        except subprocess.TimeoutExpired:
            return
        raise RuntimeError("Audio player exited before playback")

    def pause(self):
        if self.playing:
            self.process.send_signal(signal.SIGSTOP)
            self.paused = True

    def resume(self):
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("No paused song")
        if self.paused:
            self.process.send_signal(signal.SIGCONT)
            self.paused = False

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            if self.paused:
                self.process.send_signal(signal.SIGCONT)
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait()
        self.process = None
        self.paused = False

class MusicTools:
    def __init__(self, config, controller=None, library=None, player=None, clock=time.monotonic):
        self.config, self.controller, self.library = config, controller, library
        self.clock = clock
        http_config = config.get("http", {})
        provider_class = {"tang": TangMusicProvider, "fallback": FallbackMusicProvider,
                          "netease": NeteaseMusicProvider}.get(http_config.get("adapter"), HttpMusicProvider)
        self.provider = provider_class(http_config)
        self.player = player
        self.pending = []
        self.deadline = 0.0
        self.playing = False

    def clear_pending(self):
        self.pending = []
        self.deadline = 0.0

    @property
    def has_pending(self):
        if self.clock() >= self.deadline:
            self.clear_pending()
        return bool(self.pending)

    @staticmethod
    def _clean_selection(text):
        text = re.sub(r"[\s，。！？,.!?《》]+", "", text)
        text = re.sub(r"^(?:请|帮我|给我|播放|放|选择|选|我要听)+", "", text)
        return re.sub(r"(?:吧|谢谢|就这首)$", "", text)

    def selection_request(self, text):
        if not self.has_pending:
            return None
        selection = self._clean_selection(text)
        if re.fullmatch(r"第?[一二三四五六七八九十1-9][首个]?", selection):
            return selection
        if any(selection == self._clean_selection(s["title"]) for s in self.pending):
            return selection
        return None

    def search(self, query, utterance=""):
        self.clear_pending()
        if not self.config.get("enabled", False):
            return result("音乐功能目前未启用。", ok=False, status="unavailable")
        if not query.strip():
            return result("你想听哪首歌，或者哪位歌手的歌？", status="needs_input")
        if self.config.get("provider", "qqmusic") == "http":
            if not self.provider.url:
                return result("还没有配置音乐搜索接口。", ok=False, status="unavailable")
            songs = self.provider.search(query)
        else:
            if self.controller is None:
                return result("QQ音乐控制器尚未就绪。", ok=False, status="unavailable")
            matches = self.library.search(query, limit=3) if self.library else []
            songs = [dict(id=s.mid, title=s.title, artists=list(s.artists), backend="qqmusic",
                          query=query) for s in matches]
            if not songs:
                songs = self.controller.search_candidates(query, limit=3)
        if not songs:
            return result("没有找到可播放的歌曲，请换一个歌名或歌手。", status="not_found")
        self.pending = songs[:3]
        self.deadline = self.clock() + 120
        public = [{k: s.get(k) for k in ("id", "title", "artists")} for s in self.pending]
        choices = "；".join(f"{i}，{s['title']}" +
                           ("，" + "、".join(s.get("artists", [])) if s.get("artists") else "")
                           for i, s in enumerate(self.pending, 1))
        return result("找到这些歌曲：" + choices + "。你想听第几首？",
                      status="needs_selection", executed=True, candidates=public)

    def select(self, selection):
        if not self.has_pending:
            return result("歌曲列表已过期或已取消，请重新搜索。", ok=False, status="expired")
        text = self._clean_selection(selection)
        match = re.fullmatch(r"第?([一二三四五六七八九十1-9])[首个]?", text)
        if match:
            number = match.group(1)
            index = int(number) - 1 if number.isdigit() else "一二三四五六七八九十".index(number)
            matches = self.pending[index:index+1]
        else:
            matches = [s for s in self.pending if self._clean_selection(s["title"]) == text
                       or s["id"] == selection]
        if len(matches) != 1:
            return result("请用列表中的编号选择一首歌。", ok=False, status="needs_selection")
        song = matches[0]
        if song["backend"] == "http":
            expires = song.get("expires_at")
            if expires is not None and expires <= time.time():
                self.clear_pending()
                return result("播放地址已过期，请重新搜索。", ok=False, status="expired")
            if self.player is None:
                return result("音频播放器不可用。", ok=False, status="unavailable")
            url = self.provider.resolve(song) if song.get("resolver") in {"tang", "netease"} else song["url"]
            self.player.play(url)
        else:
            self.controller.play(song.get("query", song["title"]),
                                 preferred_mid=song["id"], strict_mid=True)
        self.playing = True
        self.clear_pending()
        return result("正在播放" + song["title"] + "。", executed=True, playing=True)

    def control(self, action):
        if action == "stop_music":
            self.clear_pending()
        if not self.config.get("enabled", False):
            return result("音乐功能目前未启用。", ok=False, status="unavailable")
        name = {"pause_music": "pause", "resume_music": "resume", "next_music": "next",
                "previous_music": "previous", "stop_music": "stop"}[action]
        if self.config.get("provider", "qqmusic") == "http":
            if name in {"next", "previous"}:
                return result("请先搜索并选择下一首歌曲。", ok=False, status="needs_input",
                              playing=self.playing)
            if self.player is None:
                return result("播放器不可用。", ok=False, status="unavailable")
            getattr(self.player, name)()
            self.playing = self.player.playing
        else:
            if self.controller is None:
                return result("QQ音乐控制器尚未就绪。", ok=False, status="unavailable")
            getattr(self.controller, name)()
            self.playing = name in {"resume", "next", "previous"}
        return result({"pause": "已暂停音乐。", "resume": "继续播放音乐。",
                       "next": "已切换下一首。", "previous": "已切换上一首。",
                       "stop": "已停止音乐。"}[name], executed=True, playing=self.playing)

    def close(self):
        self.clear_pending()
        if self.player is not None:
            self.player.stop()
