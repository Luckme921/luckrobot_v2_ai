"""Versioned, validated WAV assets; no network in the dialogue path."""
import hashlib
from pathlib import Path
import subprocess
import wave
from edge.audio.acknowledgement import PHRASES
WAKE_PHRASES = {"wake_here": "我在呢。", "wake_hello": "你好呀。", "wake_chat": "有什么想聊的吗？"}
GOODBYE_PHRASES = {"bye_short": "拜拜，下次聊。", "bye_hello": "那我先告退了。"}
ALL_PHRASES = {**PHRASES, **WAKE_PHRASES, **GOODBYE_PHRASES}


def play_cached_reply(clip, sink, on_playback):
    """Track the actual player lifetime for short cached voice replies."""
    on_playback(True)
    try:
        subprocess.run(["paplay", f"--device={sink}", str(clip)], check=True, timeout=15)
    finally:
        on_playback(False)

def cache_path(voice, text):
    key = hashlib.sha256(("pcm24k-v1|"+voice+"|"+text).encode()).hexdigest()[:24]
    return Path("private/tts-phrases")/(key+".wav")

def valid_clip(path):
    try:
        with wave.open(str(path), "rb") as wav:
            frames=wav.getnframes()
            return (wav.getnchannels()==1 and wav.getsampwidth()==2 and wav.getframerate()==24000
                    and 0 < frames <= 24000*15 and len(wav.readframes(frames))==frames*2)
    except (OSError, EOFError, wave.Error): return False
