"""Search -> optional direct playback -> pending candidates -> explicit choice -> trusted provider playback."""
import json
import os
import re
import random
import shutil
import signal
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

VERSION_MARKERS = (
    "live", "现场", "dj", "remix", "翻唱", "cover", "伴奏", "纯音乐",
    "吉他版", "女版", "男版", "原版", "版本", "版",
)

def result(message, *, ok=True, status="success", executed=False, playing=False, **data):
    return dict(ok=ok, status=status, executed=executed, playing=playing, message=message, **data)


def _normalize_text(value: str) -> str:
    """Strip decorative punctuation/spaces for fuzzy matching."""
    return re.sub(r"[^\w一-鿿]+", "", str(value).casefold(), flags=re.UNICODE)


def _base_song_title(value: str) -> str:
    """Remove provider-added version/cover annotations for title comparison."""
    text = re.sub(r"[（(【\[].*?[）)】\]]", "", str(value).casefold())
    text = _normalize_text(text)
    for marker in VERSION_MARKERS:
        text = text.replace(_normalize_text(marker), "")
    return text


def _extract_music_query(text: str) -> str | None:
    """Extract a local music query without asking the LLM for common phrasings."""
    value = re.sub(r"[，。！？,.!?]+$", "", str(text).strip())
    if not value or any(word in value for word in
                        ("不要", "别播放", "别放", "怎么", "为什么", "如何", "如果")):
        return None
    prefixes = (
        "麻烦你帮我", "麻烦帮我", "你可以帮我", "可以帮我", "能不能帮我",
        "我想听", "我要听", "想听", "请帮我", "帮我", "给我",
        "你可以", "可以", "能不能", "请", "播放一首", "播放", "放一首",
        "放首", "放", "来一首", "来首", "听一首", "听首", "点一首", "点首",
    )
    action_prefixes = {
        "我想听", "我要听", "想听", "播放一首", "播放", "放一首", "放首",
        "放", "来一首", "来首", "听一首", "听首", "点一首", "点首",
    }
    heard_action = False
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if value.startswith(prefix):
                value = value[len(prefix):].strip()
                heard_action = heard_action or prefix in action_prefixes
                changed = True
                break
    if not heard_action:
        return None
    value = re.sub(r"(?:给我听|来听|听听|可以吗|好吗|行吗|吧|呀|啊|呢|吗)$", "", value).strip()
    value = re.sub(r"^一首", "", value).strip()
    artist_title = re.fullmatch(r"([^的]{2,8})的(.{2,40})", value)
    if artist_title:
        value = f"{artist_title.group(1).strip()} {artist_title.group(2).strip()}"
    return value or None


def _match_score(query: str, song: dict) -> float:
    """Return 0-100 confidence that *song* is what the user asked for.

    Higher scores require both title and artist alignment so that generic
    one-word queries do not accidentally auto-play the wrong track.
    """
    q = _normalize_text(query)
    title = _normalize_text(song.get("title", ""))
    artists = [_normalize_text(a) for a in song.get("artists", []) if a]

    if not q or not title:
        return 0.0

    score = 0.0

    # Title matching
    if q == title:
        score += 80.0
    elif title in q:
        score += 60.0
    elif q in title:
        score += 35.0

    score += SequenceMatcher(None, q, title).ratio() * 20.0

    # Artist matching
    artist_hits = sum(1 for a in artists if a and a in q)
    if artist_hits:
        score += 25.0 * min(artist_hits, 2)

    # Prefer studio versions when the user did not ask for a variant.
    version_markers = VERSION_MARKERS
    title_lower = str(song.get("title", "")).casefold()
    query_lower = str(query).casefold()
    for marker in version_markers:
        if marker in title_lower and marker not in query_lower:
            score -= 12.0

    return max(0.0, min(100.0, score))


def _autoplay_candidate(query, candidates, threshold, gap):
    """Require an explicit artist/title and no competing version; never trust API order."""
    if not candidates or not 0 < threshold <= 100 or not 0 <= gap <= 100:
        return None
    ranked = sorted(candidates, key=lambda song: _match_score(query, song), reverse=True)
    top = ranked[0]
    score = _match_score(query, top)
    if score < threshold:
        return None
    if len(ranked) > 1 and score - _match_score(query, ranked[1]) < gap:
        return None
    q = _normalize_text(query)
    title = _normalize_text(top.get("title", ""))
    artists = [_normalize_text(a) for a in top.get("artists", []) if a]
    # Title-only requests cannot distinguish original singers from covers.
    if not any(q in {a + title, a + "的" + title, title + a} for a in artists):
        return None
    markers = ("live", "现场", "dj", "remix", "翻唱", "cover", "伴奏", "纯音乐", "demo", "版本", "版")
    def base(value):
        value = _normalize_text(value)
        for marker in markers:
            value = value.replace(marker, "")
        return value
    requested_variant = any(marker in q for marker in markers)
    for other in ranked[1:]:
        other_title = _normalize_text(other.get("title", ""))
        if other_title == title:
            return None
        if not requested_variant and base(other_title) == base(title):
            return None
    return top


def is_random_request(text):
    value = _normalize_text(text)
    if value in {"随便", "随便吧", "都行", "都可以", "任意", "随便一首", "随机播放",
                 "每日推荐", "推荐音乐", "随便放一首", "随便来一首"}:
        return True
    if re.fullmatch(
            r"(?:请|帮我|给我)?(?:随便|随机)?(?:播放|放|来|听|放点|放个)?"
            r"(?:一首|首|个|点|一些)?(?:歌|歌曲|音乐)"
            r"(?:吧|听听|就可以了?|就行了?|可以了?)?", value):
        return True
    # Strip only generic music/request words. Any remaining title or artist keeps
    # the request on the explicit-search path.
    generic_words = (
        "随便播放", "随机播放", "帮我播放", "给我播放", "每日推荐", "推荐音乐",
        "随便", "随机", "任意", "都可以", "都行", "什么都行", "好听的",
        "播放", "放一首", "放首", "放点", "放个", "来一首", "来首", "听一首",
        "歌曲", "音乐", "一首歌", "歌", "一首", "一些", "一个", "一下",
        "请", "帮我", "给我", "听听", "就可以了", "就可以", "就行了", "就行",
        "可以了", "可以", "吧", "呀", "啊",
    )
    remainder = value
    # Repeat because removing one phrase can expose a shorter adjacent phrase.
    previous = None
    while remainder != previous:
        previous = remainder
        for word in sorted(generic_words, key=len, reverse=True):
            remainder = remainder.replace(_normalize_text(word), "")
    has_generic_music = any(word in value for word in ("歌", "歌曲", "音乐", "播放", "放", "来首"))
    return has_generic_music and not remainder


def is_pending_random_choice(text):
    """Short replies choose an existing list; full requests start a fresh search."""
    return _normalize_text(text) in {
        _normalize_text(value) for value in
        ("随便", "随便吧", "都行", "都可以", "任意", "随便一首")
    }


def explicit_candidate(query, songs, minimum_score=0.62):
    """Pick the highest fuzzy title+artist match, including Live/Mix variants."""
    q = _normalize_text(query)
    matches = []
    markers = VERSION_MARKERS + ("mix",)

    def base(value):
        value = _normalize_text(value)
        for marker in markers:
            value = value.replace(marker, "")
        return value

    for song in songs:
        title = _normalize_text(song.get("title", ""))
        if not title:
            continue
        for artist in song.get("artists", []):
            a = _normalize_text(artist)
            aliases = [a]
            if len(a) >= 3:
                aliases.append(a[-2:])
            alias = next((item for item in aliases if item and item in q), None)
            if alias is None:
                continue
            remaining = q.replace(alias, "", 1).strip("的")
            if len(remaining) < 2:
                continue
            title_score = max(
                SequenceMatcher(None, remaining, title).ratio(),
                SequenceMatcher(None, base(remaining), base(title)).ratio(),
            )
            if base(remaining) and (
                    base(remaining) in base(title) or base(title) in base(remaining)):
                title_score = max(title_score, 0.95)
            artist_score = 1.0 if alias == a else 0.9
            matches.append((title_score * 0.8 + artist_score * 0.2, song))
            break
    matches.sort(key=lambda pair: pair[0], reverse=True)
    if not matches or matches[0][0] < minimum_score:
        return None
    return matches[0][1]


class HttpMusicProvider:
    """Adapter contract: GET search_url?q=...&limit=3 -> {"songs":[...]}."""
    def __init__(self, config):
        self.url = str(config.get("search_url", "")).strip()
        self.token_env = str(config.get("token_env", "MUSIC_API_TOKEN"))
        self.timeout = min(30.0, max(1.0, float(config.get("timeout_seconds", 10))))
        self.limit = min(20, max(3, int(config.get("search_limit", 10))))

    def search(self, query):
        if urlsplit(self.url).scheme not in {"http", "https"}:
            raise ValueError("Configure music.http.search_url first")
        headers = {"Accept": "application/json"}
        token = os.getenv(self.token_env, "")
        if token:
            headers["Authorization"] = "Bearer " + token
        joiner = "&" if "?" in self.url else "?"
        req = Request(self.url + joiner + urlencode({"q": query, "limit": self.limit}), headers=headers)
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
            if len(clean) == self.limit:
                break
        return clean

class TangMusicProvider:
    """Adapter for the QQ JSON endpoint extracted from wangye.html."""
    def __init__(self, config):
        self.url = str(config.get("search_url") or "https://tang.api.s01s.cn/music_open_api.php")
        self.timeout = min(30., max(1., float(config.get("timeout_seconds", 10))))
        self.limit = min(20, max(3, int(config.get("search_limit", 10))))

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
            if len(songs) == self.limit:
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
        data = self._request({"word": query, "page": 1, "num": self.limit})
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
            if len(songs) == self.limit: break
        return songs

    def resolve(self, song):
        if not str(song["id"]).isdigit(): raise ValueError("Invalid song ID")
        helper = TangMusicProvider({"search_url": "https://api.qijieya.cn/meting/", "timeout_seconds": self.timeout})
        data = helper._request({"type": "song", "id": song["id"]})
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise ValueError("Invalid Netease detail response")
        detail = data[0]
        search_title = _base_song_title(song["title"])
        detail_title = _base_song_title(detail.get("name", ""))
        if (not search_title or not detail_title or
                not (search_title in detail_title or detail_title in search_title or
                     SequenceMatcher(None, search_title, detail_title).ratio() >= 0.8)):
            raise ValueError("Music detail title changed")
        url = detail.get("url")
        if not isinstance(url, str) or urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).hostname:
            raise ValueError("Missing audio URL")
        return url


class FallbackMusicProvider:
    """Query all configured public providers concurrently and merge candidates."""
    def __init__(self, config):
        self.providers = {"tang": TangMusicProvider(config), "netease": NeteaseMusicProvider(config)}
        self.url = self.providers["tang"].url
        self.log_candidates = config.get("log_candidates", False) is True

    def search(self, query):
        errors = []
        found = []
        with ThreadPoolExecutor(max_workers=len(self.providers)) as executor:
            futures = {executor.submit(provider.search, query): name
                       for name, provider in self.providers.items()}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    songs = future.result()
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    errors.append(type(exc).__name__)
                    print(f"[MUSIC] SEARCH_SOURCE_FAILED provider={name} query={query!r} "
                          f"error={type(exc).__name__}", flush=True)
                    continue
                if songs:
                    print(f"[MUSIC] SEARCH_SOURCE provider={name} query={query!r} "
                          f"candidates={len(songs)}", flush=True)
                    if self.log_candidates:
                        public = [
                            {"id": song.get("id"), "title": song.get("title"),
                             "artists": song.get("artists", [])}
                            for song in songs
                        ]
                        print(
                            "[MUSIC] SEARCH_RESULTS "
                            f"provider={name} query={query!r} "
                            f"songs={json.dumps(public, ensure_ascii=False, separators=(',', ':'))}",
                            flush=True,
                        )
                    found.extend(songs)
        if not found and errors:
            raise RuntimeError("Music search services unavailable")
        unique = []
        seen = set()
        for song in found:
            key = (song.get("resolver"), song.get("id"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(song)
        return unique

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
    def __init__(self, config, controller=None, library=None, player=None, clock=time.monotonic, before_playback=None):
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
        self.before_playback = before_playback
        self.random_queries = http_config.get("random_queries", ["周杰伦", "陈奕迅", "孙燕姿"])
        preferences = config.get("preferences", {})
        self.preferred_tracks = [
            {"artist": str(item.get("artist", "")).strip(),
             "title": str(item.get("title", "")).strip()}
            for item in preferences.get("preferred_tracks", [])
            if isinstance(item, dict) and str(item.get("artist", "")).strip()
            and str(item.get("title", "")).strip()
        ]
        self.preferred_artists = [
            str(item).strip() for item in preferences.get("preferred_artists", [])
            if isinstance(item, str) and item.strip()
        ]
        self.random_search_attempts = min(
            10, max(1, int(preferences.get("search_attempts", 3))))
        self.random_play_attempts = min(
            10, max(1, int(preferences.get("candidate_play_attempts", 4))))
        self.auto_play_enabled = http_config.get("auto_play_enabled", False) is True
        self.search_limit = min(20, max(3, int(http_config.get("search_limit", 10))))
        self.pending_limit = min(10, max(3, int(http_config.get("pending_limit", 5))))
        self.fuzzy_auto_play_score = float(http_config.get("fuzzy_auto_play_score", 0.62))
        # Auto-play when the top candidate is clearly what the user asked for.
        # threshold=0 disables auto-play; default is intentionally conservative.
        self.auto_play_threshold = float(http_config.get("auto_play_threshold", 90.0))
        self.auto_play_gap = float(http_config.get("auto_play_gap", 20.0))

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
        text = re.sub(r"^(?:请|帮我|给我|播放|放|选择|选|我要听|想听|听)+", "", text)
        return re.sub(r"(?:的版本|的那首|的|吧|谢谢|就这首)$", "", text)

    @staticmethod
    def _candidate_description(song):
        artists = "、".join(song.get("artists", []))
        title = str(song.get("title", "")).strip()
        return f"{artists}的《{title}》" if artists else f"《{title}》"

    def _selection_matches(self, text):
        """Use pending titles/artists/versions as temporary ASR context."""
        wanted = _normalize_text(self._clean_selection(text))
        if len(wanted) < 2:
            return []
        scored = []
        for song in self.pending:
            title = _normalize_text(song.get("title", ""))
            base_title = _base_song_title(song.get("title", ""))
            artists = [_normalize_text(value) for value in song.get("artists", [])]
            aliases = [title, base_title, *artists]
            raw_title = str(song.get("title", "")).casefold()
            aliases.extend(_normalize_text(marker) for marker in VERSION_MARKERS
                           if marker in raw_title)
            aliases = [alias for alias in aliases if len(alias) >= 2]
            score = 0.0
            for alias in aliases:
                if wanted == alias:
                    score = max(score, 1.0)
                elif wanted in alias or alias in wanted:
                    score = max(score, 0.9)
                elif len(wanted) >= 3 and len(alias) >= 3:
                    score = max(score, SequenceMatcher(None, wanted, alias).ratio())
            if score >= 0.72:
                scored.append((score, song))
        if not scored:
            return []
        scored.sort(key=lambda pair: pair[0], reverse=True)
        best = scored[0][0]
        return [song for score, song in scored if best - score < 0.08]

    def selection_request(self, text):
        if not self.has_pending:
            return None
        if is_pending_random_choice(text): return "随便"
        if len(self.pending) == 1 and _normalize_text(text) in {"好的", "好", "就这首", "可以", "播放吧"}:
            return "第一首"
        selection = self._clean_selection(text)
        if any(selection == _normalize_text(a) for song in self.pending for a in song.get("artists", [])):
            return selection
        if re.fullmatch(r"第?[一二三四五六七八九十1-9][首个]?", selection):
            return selection
        if len(self._selection_matches(selection)) == 1:
            return text
        return None

    def local_request(self, text):
        selection = self.selection_request(text)
        if selection is not None:
            return {"name": "music_select", "arguments": {"selection": selection}}
        value = re.sub(r"[，。！？,.!?]+$", "", text.strip())
        controls = {"暂停音乐":"pause_music", "停止音乐":"stop_music", "结束播放":"stop_music",
                    "继续播放":"resume_music", "继续音乐":"resume_music"}
        if value in controls:
            return {"name":"music_control", "arguments":{"action":controls[value]}}
        if is_random_request(value):
            return {"name":"music_search", "arguments":{"query":"随便", "utterance":text}}
        query = _extract_music_query(value)
        if query:
            if _normalize_text(query) in {"歌", "歌曲", "音乐", "一首歌", "一首音乐"}:
                return {"name":"music_search", "arguments":{"query":"随便", "utterance":text}}
            return {"name":"music_search", "arguments":{"query":query,"utterance":text}}
        return None

    def _random_play(self, *, shuffle=True):
        # Bounded attempts; never ask the user to choose again after a random request.
        songs = list(self.pending)
        if shuffle:
            random.shuffle(songs)
        for song in songs[:self.random_play_attempts]:
            self.pending = [song]
            self.deadline = self.clock()+120
            try:
                answer = self.select("第一首")
                if answer["ok"] and answer["playing"]: return answer
            except Exception:
                pass
        self.clear_pending()
        return result("这次没能播放成功，稍后再试一下吧。", ok=False, status="unavailable")

    def _provider_search(self, query):
        if self.config.get("provider", "qqmusic") == "http":
            if not self.provider.url:
                raise RuntimeError("还没有配置音乐搜索接口。")
            return self.provider.search(query)
        if self.controller is None:
            raise RuntimeError("QQ音乐控制器尚未就绪。")
        matches = self.library.search(query, limit=3) if self.library else []
        songs = [dict(id=s.mid, title=s.title, artists=list(s.artists), backend="qqmusic",
                      query=query) for s in matches]
        return songs or self.controller.search_candidates(query, limit=3)

    def _random_search_and_play(self):
        tracks = list(self.preferred_tracks)
        random.shuffle(tracks)
        plans = [(f"{item['artist']} {item['title']}", item) for item in tracks]
        artists = list(self.preferred_artists or self.random_queries)
        random.shuffle(artists)
        plans.extend((artist, None) for artist in artists)
        if not plans:
            return result("还没有配置随机音乐来源。", ok=False, status="unavailable")

        for query, track in plans[:self.random_search_attempts]:
            try:
                songs = self._provider_search(query)
            except Exception as exc:
                print(f"[MUSIC] RANDOM_SEARCH_FAILED query={query!r} error={type(exc).__name__}", flush=True)
                continue
            if track is not None:
                matches = [song for song in songs
                           if explicit_candidate(query, [song], self.fuzzy_auto_play_score) is not None]
                matches.sort(key=lambda song: _match_score(query, song), reverse=True)
                songs = matches
            if not songs:
                continue
            self.pending = songs[:self.pending_limit]
            self.deadline = self.clock() + 120
            answer = self._random_play(shuffle=track is None)
            if answer.get("playing"):
                print(f"[MUSIC] RANDOM_PLAY query={query!r}", flush=True)
                return answer
        self.clear_pending()
        return result("这次没能找到可播放的常听歌曲，稍后再试一下吧。",
                      ok=False, status="unavailable")

    def search(self, query, utterance=""):
        self.clear_pending()
        if not self.config.get("enabled", False):
            return result("音乐功能目前未启用。", ok=False, status="unavailable")
        random_mode = is_random_request(utterance or query)
        if random_mode:
            return self._random_search_and_play()
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

        # Merge order depends on network completion time. Rank every provider's
        # result before choosing the visible subset.
        songs = sorted(songs, key=lambda song: _match_score(query, song), reverse=True)
        self.pending = songs[:self.pending_limit]
        self.deadline = self.clock() + 120

        # Compare every candidate returned by the provider before truncating the UI list.
        if random_mode:
            return self._random_play()
        chosen = (explicit_candidate(query, songs, self.fuzzy_auto_play_score)
                  if self.auto_play_enabled else None)
        if chosen is not None:
            self.pending = [chosen]
            print(f"[MUSIC] AUTO_PLAY title={chosen['title']!r}", flush=True)
            return self.select("第一首")

        public = [{k: s.get(k) for k in ("id", "title", "artists")} for s in self.pending]
        titles = {s["title"] for s in self.pending}
        artists = ["、".join(s.get("artists", [])) for s in self.pending]
        if len(self.pending)>1 and len(titles)==1 and all(artists) and len(set(artists))==len(artists):
            prompt = f"《{self.pending[0]['title']}》有几个版本，你想听" + "，还是".join(artists) + "的呀？"
        elif len(self.pending)==1:
            prompt = f"找到了{self._candidate_description(self.pending[0])}，要听这首吗？"
        else:
            choices = "、".join(self._candidate_description(song) for song in self.pending)
            prompt = ("我找到了" + choices +
                      "。你想听哪一首？可以直接说歌名、歌手或版本，也可以说随便一首。")
        return result(prompt, status="needs_selection", executed=True, candidates=public)

    def select(self, selection):
        if not self.has_pending:
            return result("歌曲列表已过期或已取消，请重新搜索。", ok=False, status="expired")
        if is_random_request(selection): return self._random_play()
        text = self._clean_selection(selection)
        match = re.fullmatch(r"第?([一二三四五六七八九十1-9])[首个]?", text)
        if match:
            number = match.group(1)
            index = int(number) - 1 if number.isdigit() else "一二三四五六七八九十".index(number)
            matches = self.pending[index:index+1]
        else:
            matches = ([s for s in self.pending if s["id"] == selection]
                       or self._selection_matches(text))
        if len(matches) != 1:
            return result("我还不能确定你想听哪一首，可以说歌手、歌名或版本。",
                          ok=False, status="needs_selection")
        song = matches[0]
        if song["backend"] == "http":
            expires = song.get("expires_at")
            if expires is not None and expires <= time.time():
                self.clear_pending()
                return result("播放地址已过期，请重新搜索。", ok=False, status="expired")
            if self.player is None:
                return result("音频播放器不可用。", ok=False, status="unavailable")
            try:
                url = (self.provider.resolve(song)
                       if song.get("resolver") in {"tang", "netease"} else song["url"])
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
                print(f"[MUSIC] RESOLVE_FAILED provider={song.get('resolver', 'http')} "
                      f"title={song.get('title')!r} error={type(exc).__name__} "
                      f"reason={str(exc)[:160]!r}", flush=True)
                return result(
                    f"找到了{self._candidate_description(song)}，但暂时拿不到可播放地址。你可以换一首。",
                    ok=False, status="unavailable", executed=True)
            if self.before_playback is not None:
                self.before_playback()
            try:
                self.player.play(url)
            except (OSError, ValueError, RuntimeError) as exc:
                print(f"[MUSIC] PLAY_FAILED title={song.get('title')!r} "
                      f"error={type(exc).__name__} reason={str(exc)[:160]!r}", flush=True)
                return result(
                    f"{self._candidate_description(song)}的播放地址打开失败了，可以换一首。",
                    ok=False, status="unavailable", executed=True)
        else:
            if self.before_playback is not None:
                self.before_playback()
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
