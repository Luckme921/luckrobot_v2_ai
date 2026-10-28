"""Search -> optional direct playback -> pending candidates -> explicit choice -> trusted provider playback."""
import json
import os
import re
import random
import shutil
import signal
import subprocess
import time
import threading
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from edge.music.qqmusic import QQMusicAuthRequired, QQMusicSelectionExpired
from edge.music import auth_bridge
from robot_tools.music_aliases import equivalent, load_aliases, normalize as normalize_alias

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


def _canonical_music_query(value: str) -> str:
    """Correct a known singer/title ASR pair before searching QQ Music."""
    compact = re.sub(r"[\s的]+", "", str(value).strip())
    if re.fullmatch(r"[宋孙松][冬东农]野[南安][河和]桥", compact):
        return "宋冬野 安和桥"
    return value


def _extract_music_query(text: str) -> str | None:
    """Extract a local music query without asking the LLM for common phrasings."""
    value = re.sub(r"[，。！？,.!?]+$", "", str(text).strip())
    if not value or any(word in value for word in
                        ("不要", "别播放", "别放", "怎么", "为什么", "如何", "如果")):
        return None
    prefixes = (
        "麻烦你帮我", "麻烦帮我", "你可以帮我", "可以帮我", "能不能帮我",
        "我想要听", "想要听", "我想听", "我要听", "想听", "请帮我", "帮我", "给我",
        "再帮我搜一下", "再帮我搜", "帮我搜一下", "帮我搜", "再搜一下", "再搜索",
        "搜一下", "搜索一下", "搜搜", "搜索", "再找一首", "再找首", "再找一下",
        "再找", "找一首", "找首", "找一下", "找", "换一首", "换首", "换",
        "你可以", "可以", "能不能", "请", "播放一首", "播放", "放一首",
        "放首", "放", "来一首", "来首", "听一首", "听首", "点一首", "点首",
    )
    action_prefixes = {
        "我想要听", "想要听", "我想听", "我要听", "想听", "播放一首", "播放", "放一首", "放首",
        "放", "来一首", "来首", "听一首", "听首", "点一首", "点首",
        "再帮我搜一下", "再帮我搜", "帮我搜一下", "帮我搜", "再搜一下", "再搜索",
        "搜一下", "搜索一下", "搜搜", "搜索", "再找一首", "再找首", "再找一下",
        "再找", "找一首", "找首", "找一下", "找", "换一首", "换首", "换",
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
    value = re.sub(r"(?:给我听|来听|听听|可以吗|好吗|行吗|吧|呀|啊|呢|吗)$", "", value).strip()
    value = re.sub(r"^一首", "", value).strip()
    artist_only = re.search(
        r"(?:^|[，。！？,.!?])([^，。！？,.!?]{2,12}?)(?:的)?(?:歌曲|音乐|歌)$",
        value,
    )
    if artist_only:
        value = artist_only.group(1).strip()
        heard_action = True
    if not heard_action:
        return None
    # A narrowly scoped correction for the observed ASR rendering of
    # "宋冬野的安和桥". Keep it behind an explicit music request.
    canonical = _canonical_music_query(value)
    if canonical != value:
        return canonical
    artist_title = re.fullmatch(r"([^的]{2,8})的(.{2,40})", value)
    if artist_title:
        value = f"{artist_title.group(1).strip()} {artist_title.group(2).strip()}"
    return value or None


def has_explicit_music_intent(text: str) -> bool:
    """Require an audible music cue before a fresh model-routed search."""
    value = re.sub(r"[\s，。！？,.!?]+", "", str(text)).casefold()
    if not value or any(marker in value for marker in
                        ("不要", "别播放", "别放", "怎么", "为什么", "如何", "如果")):
        return False
    if any(marker in value for marker in (
        "放一首", "放首", "放点", "放那首", "放这首", "播放", "一首歌", "一首音乐", "一首歌曲",
        "歌曲", "音乐", "小曲", "我想要听", "想要听", "我想听", "我要听", "想听", "听一首", "听首",
        "点一首", "点首", "来一首", "来首", "换歌", "换一首", "换首",
        "再来一首", "再找一首", "下一首",
    )):
        return True
    if re.search(r"(?:搜|搜索|找|换).{0,18}(?:歌曲|音乐|歌)", value):
        return True
    # A named artist/title search may omit the word "歌". The model has
    # already selected play_music; this guard only rejects wake-word noise.
    if re.search(r"(?:搜|搜索|找)(?:一下)?(?:那个|那首)?[^，。！？]{2,24}的[^，。！？]{2,20}$", value):
        return True
    return bool(re.search(r"[^的]{2,12}的(?:歌曲|音乐|歌)(?:吧)?$", value))


def _qq_candidate_matches_query(query: str, song: dict) -> bool:
    """Reject QQ's broad suggestions before offering a title-only search."""
    wanted = _normalize_text(query)
    title = _normalize_text(_base_song_title(song.get("title", "")))
    if not wanted or not title:
        return False
    if wanted == title or (len(wanted) >= 3 and wanted in title):
        return True
    if equivalent("songs", query, _base_song_title(song.get("title", ""))):
        return True
    if any(equivalent("artists", query, artist) or
           wanted == _normalize_text(artist) or
           (len(wanted) >= 3 and wanted in _normalize_text(artist))
           for artist in song.get("artists", [])):
        return True
    return len(wanted) >= 4 and SequenceMatcher(None, wanted, title).ratio() >= 0.8


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
            r"(?:一首|首|个|点|一些)?(?:歌|歌曲|音乐|小曲)"
            r"(?:吧|听听|就可以了?|就行了?|可以了?)?", value):
        return True
    # Strip only generic music/request words. Any remaining title or artist keeps
    # the request on the explicit-search path.
    generic_words = (
        "随便播放", "随机播放", "帮我播放", "给我播放", "每日推荐", "推荐音乐",
        "随便", "随机", "任意", "都可以", "都行", "什么都行", "好听的",
        "播放", "放一首", "放首", "放点", "放个", "放吧", "放", "来一首", "来首", "来点", "听一首",
        "歌曲", "音乐", "小曲", "一首歌", "歌", "一首", "一些", "一个", "一下",
        "请", "帮我", "给我", "你", "我", "听听", "就可以了", "就可以", "就行了", "就行",
        "可以了", "可以", "吧", "呀", "啊",
    )
    remainder = value
    # Repeat because removing one phrase can expose a shorter adjacent phrase.
    previous = None
    while remainder != previous:
        previous = remainder
        for word in sorted(generic_words, key=len, reverse=True):
            remainder = remainder.replace(_normalize_text(word), "")
    has_generic_music = any(word in value for word in
                            ("歌", "歌曲", "音乐", "小曲", "播放", "放", "来首"))
    return has_generic_music and not remainder


def is_pending_random_choice(text):
    """Short replies choose an existing list; full requests start a fresh search."""
    return _normalize_text(text) in {
        _normalize_text(value) for value in
        ("随便", "随便吧", "都行", "都可以", "任意", "随便一首")
    }


def is_change_music_request(text, *, has_context=False):
    """Treat conversational 'another one' as a new curated play request."""
    value = _normalize_text(text)
    if (has_context and ("不是说歌名" in value or "不是歌名" in value)
            and re.search(r"(?:换|找)(?:一首|首)", value)):
        return True
    value = re.sub(r"^(?:我不想听|不想听|这首不喜欢|随便|你)+", "", value)
    if re.fullmatch(
            r"(?:再|重新)?换(?:一首|首|个|点)?(?:别的|其他的)?(?:歌|歌曲|音乐)?",
            value):
        return True
    if re.fullmatch(r"再(?:来|找)(?:一首|首)(?:别的|其他的)?(?:歌|歌曲|音乐)?", value):
        return True
    if has_context and re.fullmatch(
            r"(?:再|重新)?(?:找|来|放|播)(?:一首|首|点|一点|一些)?"
            r"(?:别的|其他的|其他|新的)(?:歌|歌曲|音乐)?", value):
        return True
    return False


def is_recommendation_request(text):
    value = _normalize_text(text)
    if "推荐" not in value or not any(word in value for word in ("歌", "音乐", "小曲")):
        return False
    for word in ("有什么", "有没有", "能不能", "可不可以", "推荐", "好听的",
                 "歌曲", "音乐", "小曲", "一首", "几首", "一些", "的", "歌",
                 "给我", "帮我", "请", "你", "听", "吗", "呢", "吧", "呀"):
        value = value.replace(word, "")
    return not value


def needs_model_music_interpretation(text):
    """Let the model interpret incomplete descriptions after pending choices fail."""
    value = _normalize_text(text)
    return any(marker in value for marker in (
        "歌词里", "歌词有", "有一句", "唱着", "忘了歌名", "不记得歌名",
        "歌名忘了", "那首什么", "那首叫", "那首歌叫什么", "之前搜到",
        "上次搜到", "刚才搜到",
    ))


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
        # QQ appends drama/album descriptions after 《. A match inside that
        # annotation does not establish that the actual track has the title.
        primary_title = str(song.get("title", "")).split("《", 1)[0].strip()
        title = _normalize_text(primary_title)
        if not title:
            continue
        if any(marker in title and marker not in q for marker in
               ("伴奏", "纯音乐", "dj", "remix", "翻唱", "改编", "原声")):
            continue
        for artist in song.get("artists", []):
            a = _normalize_text(artist)
            aliases = [a]
            if len(a) >= 3:
                aliases.append(a[-2:])
            for canonical, variants in load_aliases()["artists"].items():
                if equivalent("artists", canonical, artist):
                    aliases.extend(normalize_alias(name) for name in [canonical, *variants])
            alias = next((item for item in aliases if item and item in q), None)
            if alias is None:
                continue
            remaining = q.replace(alias, "", 1).strip("的")
            if len(remaining) < 2:
                continue
            title_score = max(
                SequenceMatcher(None, remaining, title).ratio(),
                SequenceMatcher(None, base(remaining), base(primary_title)).ratio(),
            )
            if equivalent("songs", remaining, _base_song_title(primary_title)):
                title_score = 1.0
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
        # This endpoint often returns an empty list for Chinese artist/title
        # queries separated by spaces, while the compact form returns the
        # expected catalog rows. Preserve spaces for non-Chinese searches.
        provider_query = (re.sub(r"\s+", "", query)
                          if re.search(r"[\u4e00-\u9fff]", query) else query)
        data = self._request({"msg": provider_query, "type": "json"})
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
                              query=provider_query, backend="http", resolver="tang"))
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

    @property
    def active(self):
        """Return whether the player process still exists, including while paused."""
        return self.process is not None and self.process.poll() is None

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

def _playback_locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._playback_lock:
            return method(self, *args, **kwargs)
    return wrapped


class MusicTools:
    def __init__(self, config, controller=None, library=None, player=None, clock=time.monotonic, before_playback=None):
        self._playback_lock = threading.RLock()
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
        self.current_song = None
        # A verified user selection is a replay reference, not a pending list.
        self.last_selected_song = None
        self.recent_random_tracks = []
        self.recent_recommendations = []
        self.playlist_queue = []
        self.playlist_name = None
        self.playlist_expected = None
        self.playlist_missing_polls = 0
        self.playlist_started_at = 0.0
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
        self.known_artists = [str(item).strip() for item in preferences.get("known_artists", [])
                              if isinstance(item, str) and item.strip()]
        self.known_titles = [str(item).strip() for item in preferences.get("known_titles", [])
                             if isinstance(item, str) and item.strip()]
        self.catalog_route_enabled = config.get("catalog_route_enabled", False) is True
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

    def _normalize_artist_title_query(self, query: str) -> str:
        """Accept model queries written as '歌手的歌名' when singer is known."""
        query = str(query).strip()
        if " " in query:
            return query
        match = re.fullmatch(r"([^的]{2,30})的([^的]{2,80})", query)
        if not match:
            return query
        artist, title = (part.strip() for part in match.groups())
        known = set(self.known_artists + self.preferred_artists +
                    [item["artist"] for item in self.preferred_tracks])
        known.update(load_aliases()["artists"])
        if not any(equivalent("artists", artist, candidate) for candidate in known):
            return query
        return f"{artist} {title}"

    @property
    def has_pending(self):
        if self.clock() >= self.deadline:
            self.clear_pending()
        return bool(self.pending)

    def pending_context(self):
        """Only public candidate names and indices may be sent to the router."""
        if not self.has_pending:
            return []
        return [dict(index=index, title=str(song.get("title", ""))[:120],
                     artists=[str(artist)[:80] for artist in song.get("artists", [])[:4]])
                for index, song in enumerate(self.pending[:10], 1)]

    def stage_suggested_songs(self, reply):
        """Keep model-mentioned artist/title pairs selectable, but verify on QQ later."""
        if self.has_pending or "我找到了" not in reply:
            return False
        pairs = re.findall(r"([^，、。；\n]{2,28}?)的《([^》]{2,80})》", reply)
        suggestions = []
        seen = set()
        for raw_artist, raw_title in pairs:
            artist = re.split(r"(?:我找到了|还找到了|以及|比如)", raw_artist)[-1].strip()
            title = raw_title.strip()
            if not artist or len(artist) > 16 or not title:
                continue
            key = (_normalize_text(artist), _normalize_text(title))
            if key in seen:
                continue
            seen.add(key)
            suggestions.append(dict(id=f"suggested:{len(suggestions)}", title=title,
                                    artists=[artist], backend="recommendation",
                                    query=f"{artist} {title}"))
        if not suggestions:
            return False
        self.pending = suggestions[:self.pending_limit]
        self.deadline = self.clock() + 120
        print("[MUSIC] SUGGESTIONS_STAGED " + json.dumps(
            self.pending_context(), ensure_ascii=False, separators=(',', ':')), flush=True)
        return True

    def playback_finished(self):
        """Consume a natural HTTP-player exit and clear stale playback state."""
        if (
            self.config.get("provider", "qqmusic") == "http"
            and self.playing
            and self.player is not None
            and not self.player.active
        ):
            self.playing = False
            self.current_song = None
            return True
        return False

    @staticmethod
    def _clean_selection(text):
        text = re.sub(r"[\s，。！？,.!?《》]+", "", text)
        text = re.sub(r"^(?:请|帮我|给我|播放|放|选择|选|我要听|想听|听)+", "", text)
        text = re.sub(r"(?:的版本|的那首|的|吧|谢谢|就这首)$", "", text)
        return "宋冬野" if text in {"宋东野", "孙冬野", "松农野"} else text

    @staticmethod
    def _candidate_description(song):
        artists = "、".join(song.get("artists", []))
        title = str(song.get("title", "")).strip()
        return f"{artists}的《{title}》" if artists else f"《{title}》"

    @staticmethod
    def _display_song(song):
        return {
            "title": str(song.get("title", "")).strip(),
            "artists": [str(value).strip() for value in song.get("artists", [])
                        if str(value).strip()],
        }

    @staticmethod
    def _qq_track_metadata(track, fallback=None):
        """Use the QQ player's actual track text after playback or track change."""
        if not isinstance(track, str) or not track.strip():
            return fallback
        lines = [line.strip() for line in track.splitlines() if line.strip()]
        if not lines:
            return fallback
        if len(lines) == 1 and " - " in lines[0]:
            title, artist = lines[0].rsplit(" - ", 1)
            return {"title": title.strip(), "artists": [artist.strip()]}
        return {"title": lines[0], "artists": lines[1:3]}

    def refresh_current_track(self, track=None):
        """Return metadata only when QQ has advanced to a different song."""
        if not self.playing or self.controller is None or self.config.get("provider") != "qqmusic":
            return None
        if track is None:
            track = self.controller.current_track()
        if not self.playing:
            return None
        song = self._qq_track_metadata(track)
        if not song or (self.current_song and
                        song["title"] == self.current_song.get("title") and
                        song["artists"] == self.current_song.get("artists")):
            return None
        self.current_song = song
        print(f"[MUSIC] TRACK_CHANGED title={song['title']!r}", flush=True)
        return self._display_song(song)

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
        # A user may interrupt a spoken list with "第一首" or refer back to
        # "上一次找到的第一首". Resolve that against the retained candidates.
        ordinal = (re.search(r"第([一二三四五六七八九十1-9])[首个]", _normalize_text(text))
                   if not re.search(r"不要|别|不想|不是|为什么|怎么", text) else None)
        if ordinal:
            value = ordinal.group(1)
            index = int(value) - 1 if value.isdigit() else "一二三四五六七八九十".index(value)
            if index < len(self.pending):
                return f"第{value}首"
        spoken_number = re.search(r"(?:^|听)(0?\d{1,2}[一二三四五六七八九十\d]?)", _normalize_text(text))
        if spoken_number:
            number = spoken_number.group(1).translate(str.maketrans("一二三四五六七八九", "123456789"))
            matches = [song for song in self.pending if
                       re.match(r"0?\d{1,3}", _normalize_text(song.get("title", "")))
                       and re.match(r"0?\d{1,3}", _normalize_text(song["title"])).group() == number]
            if len(matches) == 1:
                return matches[0]["id"]
        spoken = _normalize_text(text)
        title_matches = []
        for song in self.pending:
            raw_title = str(song.get("title", ""))
            primary_title = raw_title.split("《", 1)[0].strip() or raw_title
            title = _normalize_text(primary_title)
            if len(title) >= 3 and title in spoken:
                title_matches.append(song)
        if len(title_matches) == 1:
            return title_matches[0]["id"]
        artist_matches = [song for song in self.pending if any(
            len(_normalize_text(artist)) >= 3 and _normalize_text(artist) in spoken
            for artist in song.get("artists", []))]
        if len(artist_matches) == 1:
            return artist_matches[0]["id"]
        if len(self.pending) == 1 and _normalize_text(text) in {"好的", "好", "就这首", "可以", "播放吧"}:
            return "第一首"
        selection = self._clean_selection(text)
        if any(_normalize_text(selection) in _normalize_text(a)
               for song in self.pending for a in song.get("artists", [])):
            return selection
        if re.fullmatch(r"第?[一二三四五六七八九十1-9][首个]?", selection):
            return selection
        if len(self._selection_matches(selection)) == 1:
            return text
        return None

    def local_request(self, text):
        value = re.sub(r"[，。！？,.!?]+$", "", text.strip())
        normalized = _normalize_text(value)
        if re.search(r"(?:晚安(?:喽|啦|了)?|拜拜|再见|结束对话)$", normalized):
            return None
        playlist = self._requested_playlist(value)
        if playlist is not None and "推荐" in normalized:
            return {"name": "music_search", "arguments": {"query": "推荐", "utterance": text}}
        if playlist is not None and any(word in normalized for word in ("播放", "放", "听")):
            return {"name": "music_search", "arguments": {"query": "歌单", "utterance": text}}
        if normalized in {"推荐几首", "推荐几首歌", "推荐几首歌曲", "推荐几首音乐"}:
            return {"name": "music_search", "arguments": {"query": "推荐", "utterance": text}}
        if any(phrase in normalized for phrase in (
                "找一点其他", "找一些其他", "找点其他", "再找一点其他",
                "再找一些", "找几首", "推荐几首", "找点别的")):
            return None
        controls = {
            "暂停音乐": "pause_music", "暂停播放": "pause_music", "暂停歌曲": "pause_music",
            "关闭音乐": "stop_music", "关掉音乐": "stop_music", "音乐关掉": "stop_music",
            "停止音乐": "stop_music", "停止播放": "stop_music", "结束播放": "stop_music",
            "停止放歌": "stop_music", "别放了": "stop_music", "不要放了": "stop_music",
            "把音乐关了": "stop_music", "把歌关了": "stop_music", "关掉歌曲": "stop_music",
            "继续播放": "resume_music", "继续音乐": "resume_music",
        }
        if normalized in controls:
            return {"name": "music_control", "arguments": {"action": controls[normalized]}}
        artist_mentioned = bool(self.last_selected_song and any(
            _normalize_text(artist) in normalized
            for artist in self.last_selected_song.get("artists", [])))
        replay_reference = (re.fullmatch(
            r"(?:你)?(?:再|重新)?(?:播放|放|听)(?:一遍|一次|一下)?(?:刚才|之前)?(?:的|那)?(?:一首|那首|首)?(?:歌|歌曲)?(?:吧)?",
            normalized) or (
            any(word in normalized for word in ("刚才", "之前", "上次", "那首"))
            and any(word in normalized for word in ("播放", "放", "想听", "要听"))
            and not any(word in normalized for word in ("记得", "为什么", "怎么", "吗"))
            and (artist_mentioned or re.search(
                r"(?:刚才|之前|上次)(?:的)?(?:那首|一首|首|让你放的)", normalized))
        ))
        if self.last_selected_song and replay_reference:
            song = self.last_selected_song
            title = song["title"].split("《", 1)[0].strip() or song["title"]
            query = " ".join([*song.get("artists", [])[:1], title]).strip()
            return {"name": "music_search", "arguments": {"query": query, "utterance": text}}
        if is_change_music_request(value, has_context=(
                self.playing or self.current_song is not None or self.has_pending)):
            return {"name": "music_search", "arguments": {"query": "随便", "utterance": text}}
        # A conversational instruction is not a QQ search term. Route it with
        # context so the model can decide whether to resume, recommend or play.
        if any(phrase in normalized for phrase in (
                "继续播放刚才", "继续放刚才", "之前的歌", "刚才的歌")):
            if normalized in {"继续播放刚才的歌曲", "继续播放刚才的歌",
                              "继续放刚才的歌曲", "继续放刚才的歌"}:
                return {"name": "music_control", "arguments": {"action": "resume_music"}}
            return None
        selection = self.selection_request(text)
        if selection is not None:
            return {"name": "music_select", "arguments": {"selection": selection}}
        if any(phrase in normalized for phrase in ("再找点其他歌", "再找些其他歌", "换点别的歌", "换一首别的歌")):
            return {"name": "music_search", "arguments": {"query": "随便", "utterance": text}}
        if needs_model_music_interpretation(value):
            return None
        if is_recommendation_request(value):
            return {"name": "music_search", "arguments": {"query": "推荐", "utterance": text}}
        if _normalize_text(value) in {
            "换歌", "换一首", "换首", "换一首歌", "换一首歌曲", "换个歌",
            "再来一首", "再来首", "再找一首", "再找首", "再找一首歌",
            "再找一首歌曲", "下一首", "下一首歌",
        }:
            return {"name":"music_search", "arguments":{"query":"随便", "utterance":text}}
        if self.catalog_route_enabled and any(phrase in normalized for phrase in (
                "好听的歌", "好听的音乐", "震撼全场", "振奋的音乐", "有氛围的歌")):
            if not any(word in normalized for word in ("随便", "随机", "任意")):
                return None
        if is_random_request(value):
            return {"name":"music_search", "arguments":{"query":"随便", "utterance":text}}
        query = _extract_music_query(value)
        if query:
            if any(token in _normalize_text(query) for token in (
                    "其他", "别的", "刚才", "之前", "继续", "再去找", "推荐")):
                return None
            if _normalize_text(query) in {"歌", "歌曲", "音乐", "一首歌", "一首音乐"}:
                return {"name":"music_search", "arguments":{"query":"随便", "utterance":text}}
            if self.catalog_route_enabled and not self._known_music_query(query):
                return None
            return {"name":"music_search", "arguments":{"query":query,"utterance":text}}
        return None

    def _known_music_query(self, query):
        """Only fast-route names present in curated seeds or a cached personal library.

        Artists and titles are independent vocabularies: a requested pair need
        not have appeared together in the cache. QQ still verifies the result.
        """
        artists = set(self.preferred_artists) | set(self.known_artists)
        titles = set(self.known_titles) | {item["title"] for item in self.preferred_tracks}
        artists.update(item["artist"] for item in self.preferred_tracks)
        if self.library:
            for playlist in self.library.data.get("playlists", {}).values():
                for song in playlist.get("songs", []):
                    artists.update(song.get("artists") or [])
                    if song.get("title"):
                        titles.add(song["title"])
        normalized = _normalize_text(query)
        # Ignore short names inside descriptive language (e.g. 歌, 好听).
        for artist in artists:
            name = _normalize_text(artist)
            if len(name) >= 2 and (normalized == name or re.search(
                    rf"(?:^|的){re.escape(name)}(?:的(?:歌|歌曲|音乐)?|$)", normalized)):
                return True
        for title in titles:
            name = _normalize_text(_base_song_title(title))
            if len(name) >= 2 and name not in {"音乐", "歌曲", "好听", "推荐"}:
                if normalized == name or (len(name) >= 3 and name in normalized):
                    return True
        return False

    def _requested_playlist(self, text):
        if self.library is None:
            return None
        value = _normalize_text(text)
        if not ("歌单" in value or "我喜欢" in value):
            return None
        names = self.library.playlist_names()
        if not isinstance(names, list):
            return None
        matches = [name for name in names if _normalize_text(name) in value]
        if matches:
            return max(matches, key=lambda name: len(_normalize_text(name)))
        if "我的歌单" in value or "个人歌单" in value:
            return "*"  # all cached personal playlists
        return None

    @staticmethod
    def _song_key(song):
        return _normalize_text("".join(song.get("artists", [])[:1]) +
                               _base_song_title(song.get("title", "")))

    @staticmethod
    def _recommendable_song(song):
        title = str(song.get("title", ""))
        return (len(title) <= 80 and not re.search(
            r"第\s*\d+\s*[集章节回]|有声书|有声小说|听书", title))

    def _personal_candidates(self, playlist_name=None):
        if self.library is None:
            return []
        seen, songs = set(), []
        for playlist in self.library.data.get("playlists", {}).values():
            if playlist_name not in (None, "*") and playlist.get("name") != playlist_name:
                continue
            for item in playlist.get("songs", []):
                mid = str(item.get("mid") or "")
                title = str(item.get("title") or "").strip()
                artists = [str(a).strip() for a in item.get("artists", []) if str(a).strip()]
                if not mid or not title or not artists or mid in seen:
                    continue
                seen.add(mid)
                songs.append(dict(id=mid, title=title, artists=artists,
                                  backend="qqmusic", query=f"{artists[0]} {title}"))
        return songs

    def _clear_playlist(self):
        self.playlist_queue = []
        self.playlist_name = None
        self.playlist_expected = None
        self.playlist_missing_polls = 0

    def _play_playlist(self, name):
        songs = self._personal_candidates(name)
        if not songs:
            return result("这个歌单还没有可播放的歌曲，请先同步 QQ 音乐歌单。",
                          status="not_found")
        # A repeated request starts at a different song while retaining playlist order.
        start = next((i for i, song in enumerate(songs)
                      if self._song_key(song) not in self.recent_random_tracks), 0)
        ordered = songs[start:] + songs[:start]
        self._clear_playlist()
        for index, song in enumerate(ordered[:3]):
            self.pending = [song]
            self.deadline = self.clock() + 120
            answer = self.select("第一首")
            if answer.get("playing"):
                self.playlist_queue = ordered[index + 1:]
                self.playlist_name = name
                self.playlist_expected = dict(self.current_song or {})
                self.playlist_started_at = time.monotonic()
                self.recent_random_tracks = (self.recent_random_tracks +
                                             [self._song_key(song)])[-20:]
                print(f"[MUSIC] PLAYLIST_START name={name!r} queued={len(self.playlist_queue)}",
                      flush=True)
                return answer
        return result("这个歌单里的歌曲暂时无法播放，请稍后再试。",
                      ok=False, status="unavailable")

    @_playback_locked
    def advance_playlist_if_needed(self, observed_track):
        """Follow the cached playlist when QQ's browser advances or stops."""
        if self.playlist_name is None or not self.playing:
            return None
        actual = self._qq_track_metadata(observed_track)
        expected = self.playlist_expected or {}
        same_title = (actual and _normalize_text(actual.get("title", "")) ==
                      _normalize_text(expected.get("title", "")))
        actual_artists = actual.get("artists", []) if actual else []
        expected_artists = expected.get("artists", [])
        same_artist = (not actual_artists or not expected_artists or
                       _normalize_text(actual_artists[0]) ==
                       _normalize_text(expected_artists[0]))
        if same_title and same_artist:
            self.playlist_missing_polls = 0
            return None
        if not actual:
            self.playlist_missing_polls += 1
            if self.playlist_missing_polls < 2 or time.monotonic() - self.playlist_started_at < 5:
                return None
        if not self.playlist_queue:
            self._clear_playlist()
            try:
                self.controller.stop()
            except (OSError, RuntimeError):
                pass
            self.playing = False
            self.current_song = None
            print("[MUSIC] PLAYLIST_FINISHED", flush=True)
            return result("歌单已经播放完了。", executed=True, playing=False, music=None)
        return self._play_next_playlist()

    def _play_next_playlist(self):
        for _ in range(min(3, len(self.playlist_queue))):
            song = self.playlist_queue.pop(0)
            self.pending = [song]
            self.deadline = self.clock() + 120
            answer = self.select("第一首")
            if answer.get("playing"):
                self.playlist_expected = dict(self.current_song or {})
                self.playlist_started_at = time.monotonic()
                self.playlist_missing_polls = 0
                self.recent_random_tracks = (self.recent_random_tracks +
                                             [self._song_key(song)])[-20:]
                print(f"[MUSIC] PLAYLIST_ADVANCE name={self.playlist_name!r} "
                      f"remaining={len(self.playlist_queue)}", flush=True)
                return answer
        self._clear_playlist()
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

    def _try_personal_random(self):
        personal = [song for song in self._personal_candidates()
                    if self._recommendable_song(song)]
        random.shuffle(personal)
        fresh_personal = [song for song in personal
                          if self._song_key(song) not in self.recent_random_tracks]
        for song in (fresh_personal or personal)[:self.random_search_attempts]:
            self.pending = [song]
            self.deadline = self.clock() + 120
            answer = self.select("第一首")
            if answer.get("playing"):
                self.recent_random_tracks = (self.recent_random_tracks +
                                             [self._song_key(song)])[-20:]
                print(f"[MUSIC] RANDOM_PLAY source=personal title={song['title']!r}",
                      flush=True)
                return answer
        return None

    def _random_search_and_play(self):
        personal_first = random.random() < 0.5
        if personal_first:
            answer = self._try_personal_random()
            if answer is not None:
                return answer
        tracks = list(self.preferred_tracks)
        random.shuffle(tracks)
        if len(tracks) > 1:
            fresh = [track for track in tracks if
                     _normalize_text(track["artist"] + track["title"])
                     not in self.recent_random_tracks]
            if fresh:
                tracks = fresh
        plans = [(f"{item['artist']} {item['title']}", item) for item in tracks]
        # Broad artist-only searches can include audiobooks and unrelated
        # recordings. Use that legacy fallback only if no curated track exists.
        if not plans:
            artists = list(self.preferred_artists or self.random_queries)
            random.shuffle(artists)
            plans.extend((artist, None) for artist in artists)
        if not plans:
            if not personal_first:
                answer = self._try_personal_random()
                if answer is not None:
                    return answer
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
                if track is not None:
                    key = _normalize_text(track["artist"] + track["title"])
                    self.recent_random_tracks = (
                        [item for item in self.recent_random_tracks if item != key]
                        + [key])[-20:]
                print(f"[MUSIC] RANDOM_PLAY query={query!r}", flush=True)
                return answer
        if not personal_first:
            answer = self._try_personal_random()
            if answer is not None:
                return answer
        self.clear_pending()
        return result("这次没能找到可播放的常听歌曲，稍后再试一下吧。",
                      ok=False, status="unavailable")

    def _recommend(self, playlist_name=None, count=3):
        personal = [song for song in self._personal_candidates(playlist_name)
                    if self._recommendable_song(song)]
        curated = [] if playlist_name else [
            dict(id=f"recommend:{index}", title=track["title"],
                 artists=[track["artist"]], backend="recommendation",
                 query=f"{track['artist']} {track['title']}")
            for index, track in enumerate(self.preferred_tracks)]
        random.shuffle(personal)
        random.shuffle(curated)
        recent = set(self.recent_recommendations) | set(self.recent_random_tracks)
        def fresh(items):
            return [song for song in items if self._song_key(song) not in recent]
        # A generic recommendation includes both the personal library and
        # curated seeds when both exist, instead of drowning seeds in a large cache.
        chosen, seen = [], set()
        sources = ([fresh(personal), fresh(curated), personal, curated]
                   if playlist_name is None else [fresh(personal), personal])
        if playlist_name is None and personal and curated and count >= 2:
            for source in sources[:2]:
                if source:
                    song = source[0]
                    chosen.append(song)
                    seen.add(self._song_key(song))
        for source in sources:
            for song in source:
                key = self._song_key(song)
                if key and key not in seen:
                    chosen.append(song)
                    seen.add(key)
                    if len(chosen) >= count:
                        break
            if len(chosen) >= count:
                break
        if not chosen:
            return result("个人歌单和偏好曲目中还没有可推荐的歌曲。",
                          ok=False, status="unavailable")
        self.pending = chosen[:count]
        self.recent_recommendations = (self.recent_recommendations +
                                       [self._song_key(song) for song in self.pending])[-30:]
        self.deadline = self.clock() + 120
        choices = "、".join(self._candidate_description(song) for song in self.pending)
        return result(f"可以听听{choices}。你想听哪首？", status="needs_selection",
                      executed=True, candidates=[self._display_song(song) for song in self.pending])

    def search(self, query, utterance=""):
        self.clear_pending()
        if not self.config.get("enabled", False):
            return result("音乐功能目前未启用。", ok=False, status="unavailable")
        playlist_name = self._requested_playlist(utterance or query)
        if playlist_name is not None and "推荐" in _normalize_text(utterance or query):
            self._clear_playlist()
            return self._recommend(playlist_name)
        if playlist_name is not None and any(word in _normalize_text(utterance or query)
                                             for word in ("播放", "放", "听")):
            return self._play_playlist(playlist_name)
        self._clear_playlist()
        if query == "推荐" or is_recommendation_request(utterance or query):
            return self._recommend()
        random_mode = is_random_request(query) or is_random_request(utterance)
        if random_mode:
            return self._random_search_and_play()
        query = self._normalize_artist_title_query(_canonical_music_query(query))
        if not query.strip():
            return result("你想听哪首歌，或者哪位歌手的歌？", status="needs_input")
        if self.config.get("provider", "qqmusic") == "http":
            if not self.provider.url:
                return result("还没有配置音乐搜索接口。", ok=False, status="unavailable")
            songs = self.provider.search(query)
        else:
            if self.controller is None:
                return result("QQ音乐控制器尚未就绪。", ok=False, status="unavailable")
            library_started = time.monotonic()
            matches = self.library.search(query, limit=3) if self.library else []
            library_seconds = time.monotonic() - library_started
            songs = [dict(id=s.mid, title=s.title, artists=list(s.artists), backend="qqmusic",
                          query=query) for s in matches
                     if " " in query or _qq_candidate_matches_query(
                         query, {"title": s.title, "artists": s.artists})]
            if not songs:
                try:
                    qq_started = time.monotonic()
                    songs = self.controller.search_candidates(
                        query, limit=12 if " " not in query else 3)
                    print(f"[MUSIC] SEARCH_TIMING query={query!r} "
                          f"library={library_seconds:.3f}s qq={time.monotonic() - qq_started:.3f}s "
                          f"candidates={len(songs)}", flush=True)
                except QQMusicAuthRequired:
                    auth_bridge.publish("required", detail="QQ 音乐登录已失效，请在屏幕上扫码登录")
                    return result("QQ 音乐需要重新登录，请点击屏幕右上角的登录入口扫码。",
                                  ok=False, status="auth_required")
        if not songs:
            return result("没有找到可播放的歌曲，请换一个歌名或歌手。", status="not_found")

        if self.config.get("provider", "qqmusic") == "qqmusic" and " " not in query:
            print(f"[MUSIC] QQ_CANDIDATES query={query!r} "
                  f"items={[(str(song.get('title', ''))[:50], [str(a)[:30] for a in song.get('artists', [])]) for song in songs[:12]]!r}",
                  flush=True)
            songs = [song for song in songs if _qq_candidate_matches_query(query, song)]
            if not songs:
                return result("QQ 音乐没有找到这首歌，搜索结果只有不相关的歌曲。",
                              status="not_found")

        if self.config.get("provider", "qqmusic") == "qqmusic" and " " in query:
            # A singer/title request must not surface unrelated QQ search
            # results merely because the page has a populated result list.
            songs = [song for song in songs if
                     explicit_candidate(query, [song], self.fuzzy_auto_play_score)]
            if not songs:
                try:
                    fresh = self.controller.search_candidates(query, limit=3)
                except QQMusicAuthRequired:
                    auth_bridge.publish("required", detail="QQ 音乐登录已失效，请在屏幕上扫码登录")
                    return result("QQ 音乐需要重新登录，请点击屏幕右上角的登录入口扫码。",
                                  ok=False, status="auth_required")
                songs = [song for song in fresh if
                         explicit_candidate(query, [song], self.fuzzy_auto_play_score)]
            if not songs:
                return result("没有找到这位歌手的这首歌，请再说一次歌手和歌名。",
                              status="not_found")

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

    @_playback_locked
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
        self.last_selected_song = self._display_song(song)
        if song["backend"] == "recommendation":
            try:
                candidates = self._provider_search(song["query"])
            except (OSError, RuntimeError) as exc:
                print(f"[MUSIC] RECOMMEND_SEARCH_FAILED error={type(exc).__name__}", flush=True)
                self.clear_pending()
                return result("这首推荐曲目暂时搜索失败了，请换一首。",
                              ok=False, status="unavailable")
            chosen = explicit_candidate(song["query"], candidates, self.fuzzy_auto_play_score)
            if chosen is None and self.config.get("provider", "qqmusic") == "qqmusic":
                try:
                    candidates = self.controller.search_candidates(song["query"], limit=3)
                    chosen = explicit_candidate(song["query"], candidates, self.fuzzy_auto_play_score)
                except (OSError, RuntimeError) as exc:
                    print(f"[MUSIC] RECOMMEND_SEARCH_FAILED error={type(exc).__name__}", flush=True)
                    self.clear_pending()
                    return result("这首推荐曲目暂时搜索失败了，请换一首。",
                                  ok=False, status="unavailable")
            if chosen is None:
                self.clear_pending()
                return result("QQ 音乐没有找到这位歌手的这首推荐曲目，请换一首。",
                              ok=False, status="not_found")
            self.pending = [chosen]
            self.deadline = self.clock() + 120
            return self.select("第一首")
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
            try:
                play_query = song.get("query", song["title"])
                try:
                    actual_track = self.controller.play(play_query,
                                                        preferred_mid=song["id"], strict_mid=True)
                except QQMusicSelectionExpired:
                    # A personal-library MID may be absent from QQ's current
                    # search page. Retry only a newly verified title/artist MID.
                    candidates = self.controller.search_candidates(play_query, limit=12)
                    expected_title = _normalize_text(_base_song_title(
                        str(song["title"]).split("《", 1)[0]))
                    expected_artists = song.get("artists", [])
                    selected_markers = [marker for marker in VERSION_MARKERS
                                        if marker in str(song["title"]).casefold()]
                    verified = [candidate for candidate in candidates
                                if _normalize_text(_base_song_title(
                                    str(candidate.get("title", "")).split("《", 1)[0])) == expected_title
                                and any(equivalent("artists", expected, actual)
                                        for expected in expected_artists
                                        for actual in candidate.get("artists", []))
                                and all(marker in str(candidate.get("title", "")).casefold()
                                        for marker in selected_markers)]
                    if not verified:
                        raise
                    verified.sort(key=lambda candidate: (
                        _normalize_text(candidate.get("title", "")) !=
                        _normalize_text(song["title"]),
                        len(str(candidate.get("title", "")))))
                    replacement = verified[0]
                    print(f"[MUSIC] QQ_MID_RETRY title={song['title']!r} "
                          f"old_mid={song['id']} new_mid={replacement['id']}", flush=True)
                    actual_track = self.controller.play(play_query,
                                                        preferred_mid=replacement["id"], strict_mid=True)
            except (OSError, RuntimeError) as exc:
                print(f"[MUSIC] QQ_PLAY_FAILED title={song.get('title')!r} "
                      f"error={type(exc).__name__} reason={str(exc)[:160]!r} "
                      f"cause={type(exc.__cause__).__name__ if exc.__cause__ else 'none'}",
                      flush=True)
                try:
                    self.controller.stop()
                except (OSError, RuntimeError) as stop_exc:
                    print(f"[MUSIC] QQ_STOP_AFTER_FAILURE_FAILED "
                          f"error={type(stop_exc).__name__}", flush=True)
                self.playing = False
                self.current_song = None
                self.clear_pending()
                return result("找到了歌曲，但 QQ 音乐没有完成播放；我已停止播放器。请稍后再试。",
                              ok=False, status="unavailable", executed=True)
            actual_song = self._qq_track_metadata(actual_track)
            expected_title = _base_song_title(str(song["title"]).split("《", 1)[0])
            actual_title = _base_song_title(actual_song["title"]) if actual_song else ""
            if (actual_title and expected_title
                    and expected_title not in actual_title
                    and actual_title not in expected_title):
                print(f"[MUSIC] TRACK_MISMATCH selected={song['title']!r} actual={actual_track!r}",
                      flush=True)
                try:
                    self.controller.stop()
                except (OSError, RuntimeError):
                    pass
                self.playing = False
                self.current_song = None
                self.clear_pending()
                return result("QQ 音乐播放了另一首歌，我已停止播放；请稍后重试。",
                              ok=False, status="mismatch", executed=True)
        self.playing = True
        self.current_song = (self._qq_track_metadata(actual_track, self._display_song(song))
                             if song["backend"] == "qqmusic" else self._display_song(song))
        if song["backend"] == "qqmusic":
            print(f"[MUSIC] NOW_PLAYING source=qq track={actual_track!r} "
                  f"selected={song['title']!r}", flush=True)
        self.clear_pending()
        return result("正在播放" + self.current_song["title"] + "。", executed=True, playing=True,
                      music=self.current_song)

    @_playback_locked
    def pause_for_conversation(self):
        """Pause the actual backend even if runtime bookkeeping says not playing."""
        if not self.config.get("enabled", False):
            return result("", playing=False, music=self.current_song)
        if self.config.get("provider", "qqmusic") == "http":
            if self.player is not None and self.player.active:
                self.player.pause()
        elif self.controller is not None and self.controller.running:
            self.controller.pause()
        self.playing = False  # Only mark paused after backend succeeds.
        return result("已暂停音乐。", executed=True, playing=False, music=self.current_song)

    @_playback_locked
    def control(self, action):
        if action == "stop_music":
            self.clear_pending()
            self._clear_playlist()
        if action == "next_music" and self.playlist_queue:
            return self._play_next_playlist() or result(
                "下一首暂时播放不了。", ok=False, status="unavailable")
        if action == "next_music" and self.playlist_name is not None:
            return self.control("stop_music")
        if action == "previous_music":
            self._clear_playlist()
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
            actual_track = getattr(self.controller, name)()
            self.playing = name in {"resume", "next", "previous"}
            if name in {"next", "previous", "resume"}:
                self.current_song = self._qq_track_metadata(
                    actual_track, self.current_song if name == "resume" else None)
                print(f"[MUSIC] NOW_PLAYING source=qq action={name} "
                      f"track={actual_track!r}", flush=True)
        if name == "stop":
            self.current_song = None
        return result({"pause": "已暂停音乐。", "resume": "继续播放音乐。",
                       "next": "已切换下一首。", "previous": "已切换上一首。",
                       "stop": "已停止音乐。"}[name], executed=True, playing=self.playing,
                      music=self.current_song)

    def close(self):
        self.clear_pending()
        self._clear_playlist()
        self.current_song = None
        if self.player is not None:
            self.player.stop()
