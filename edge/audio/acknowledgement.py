"""Cached tool acknowledgements, independent of model/tool execution."""
import subprocess
import threading
import time
import re
import wave
from array import array
from shared.timing import record

PHRASES = {
    "web_search": "我帮你查一下。",
    "web_search_alt": "让我找一找。",
    "web_search_more": "我帮你搜索一下。",
    "get_weather": "我帮你查一下天气。",
    "get_weather_alt": "我看看天气怎么样。",
    "get_weather_more": "稍等，我查查天气。",
    "request_vision": "我看一下。",
    "request_vision_alt": "我来仔细看看。",
    "request_vision_more": "让我看看你说的是什么。",
    "play_music": "我帮你找一下音乐。",
    "play_music_alt": "让我找找这首歌。",
    "play_music_more": "稍等，我看看有哪些歌。",
    "music_artist_prefix": "你想听",
    "music_artist_suffix": "的歌呀，我帮你找一下。",
    "navigate_to": "我检查一下导航请求。",
}


def music_artist_from_utterance(text):
    match = re.search(
        r"(?:有没有|想听|播放|放|听听|找|推荐)([\u4e00-\u9fffA-Za-z0-9·]{2,8})的歌",
        str(text),
    )
    return match.group(1) if match else None


def _trim_pcm(pcm, *, leading=False, trailing=False, sample_rate=24000):
    samples = array("h")
    samples.frombytes(pcm)
    active = [i for i, value in enumerate(samples) if abs(value) > 200]
    if not active:
        return pcm
    margin = int(sample_rate * 0.025)
    start = max(0, active[0] - margin) if leading else 0
    end = min(len(samples), active[-1] + margin + 1) if trailing else len(samples)
    return samples[start:end].tobytes()


def _clip_pcm(path):
    with wave.open(str(path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 24000):
            raise ValueError("Contextual acknowledgement clip format mismatch")
        return wav.readframes(wav.getnframes())

class ToolAcknowledgement:
    def __init__(self, clips, sink, delay_seconds=0.35, *, dynamic_synth=None,
                 dynamic_wait_seconds=1.5):
        self.clips = clips
        self.sink = sink
        self.delay = max(0.0, float(delay_seconds))
        self._lock = threading.Lock()
        self._timer = None
        self._process = None
        self._seen = False
        self._closed = True
        self._generation = 0
        self.played = False
        self._phrase_index = {}
        self.dynamic_synth = dynamic_synth
        self.dynamic_wait_seconds = max(0.0, float(dynamic_wait_seconds))
        self._dynamic = None

    def begin_turn(self, utterance=""):
        self.finish()
        with self._lock:
            self._generation += 1
            self._closed = False
            self._seen = False
            self.played = False
            artist = music_artist_from_utterance(utterance) if self.dynamic_synth else None
            self._dynamic = ({"artist": artist, "ready": threading.Event(), "audio": None}
                             if artist and all(key in self.clips for key in
                                               ("music_artist_prefix", "music_artist_suffix")) else None)
            dynamic = self._dynamic
        if dynamic is not None:
            def prepare():
                try:
                    dynamic["audio"] = self.dynamic_synth(dynamic["artist"])
                except Exception as exc:
                    print(f"[ACK] DYNAMIC_FALLBACK error={type(exc).__name__}", flush=True)
                finally:
                    dynamic["ready"].set()
            threading.Thread(target=prepare, name="music-ack-artist", daemon=True).start()

    def on_event(self, event):
        if event.get("type") != "tool_start":
            return
        action = event.get("action")
        variants = [key for key in (action, f"{action}_alt", f"{action}_more")
                    if key in self.clips]
        if not variants:
            return
        with self._lock:
            if self._closed or self._seen or self.sink == "<unavailable>":
                return
            index = self._phrase_index.get(action, 0)
            self._phrase_index[action] = index + 1
            key = variants[index % len(variants)]
            path = self.clips[key]
            self._seen = True
            dynamic = self._dynamic if action == "play_music" else None
            print(f"[ACK] SELECT action={action} clip={key} dynamic={bool(dynamic)}", flush=True)
            self._timer = threading.Timer(
                self.delay, self._play, args=(path, self._generation, dynamic))
            self._timer.daemon = True
            self._timer.start()

    def _play(self, path, generation, dynamic=None):
        pcm = None
        if dynamic is not None and dynamic["ready"].wait(self.dynamic_wait_seconds):
            audio = dynamic["audio"]
            if audio is not None:
                try:
                    if audio.sample_rate != 24000:
                        raise ValueError("Dynamic music acknowledgement sample rate mismatch")
                    pcm = ( _trim_pcm(_clip_pcm(self.clips["music_artist_prefix"]), trailing=True)
                           + _trim_pcm(audio.pcm, leading=True, trailing=True)
                           + _trim_pcm(_clip_pcm(self.clips["music_artist_suffix"]), leading=True) )
                except (OSError, ValueError, wave.Error) as exc:
                    print(f"[ACK] DYNAMIC_FALLBACK error={type(exc).__name__}", flush=True)
        with self._lock:
            if self._closed or generation != self._generation:
                return
            try:
                if pcm:
                    self._process = subprocess.Popen(
                        ["pacat", "--playback", "--raw", f"--device={self.sink}",
                         "--format=s16le", "--rate=24000", "--channels=1"],
                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
                    print(f"[ACK] PLAY mode=contextual artist={dynamic['artist']}", flush=True)
                else:
                    self._process = subprocess.Popen(
                        ["paplay", f"--device={self.sink}", str(path)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(f"[ACK] PLAY mode=cached clip={path}", flush=True)
                self.played = True
                process = self._process
            except OSError as exc:
                print(f"[ACK] playback unavailable: {type(exc).__name__}", flush=True)
                return
        if pcm:
            try:
                process.stdin.write(pcm)
                process.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                print("[ACK] DYNAMIC_PLAY_INTERRUPTED", flush=True)

    def finish(self):
        """Cancel unstarted speech; drain a started short clip before final TTS."""
        with self._lock:
            self._closed = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            process, self._process = self._process, None
        if process is not None:
            started = time.monotonic()
            try:
                process.wait(timeout=4.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            record("ack_drain", time.monotonic() - started)
