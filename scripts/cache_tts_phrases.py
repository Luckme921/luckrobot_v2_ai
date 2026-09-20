"""Generate fixed Edge phrases once. No playback; existing valid assets are reused."""
import os
import signal
import json
from pathlib import Path
import subprocess
import sys
import wave
import yaml
from edge.audio.tts.phrase_cache import ALL_PHRASES, cache_path, valid_clip

def main():
    cfg=yaml.safe_load(Path("configs/audio.yaml").read_text())["tts"]
    voice=cfg.get("edge_voice","zh-CN-XiaoxiaoNeural")
    interpreter=str(Path(cfg.get("edge_python","private/tts-eval-venv/bin/python")).absolute())
    failures=0
    for name,text in ALL_PHRASES.items():
        path=cache_path(voice,text);path.parent.mkdir(parents=True,exist_ok=True)
        if valid_clip(path):
            print(f"[CACHE] EXISTS {name}",flush=True);continue
        try:
            worker=subprocess.Popen([interpreter,"edge/audio/tts/edge_worker.py"],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
            try:
                pcm,_=worker.communicate(json.dumps({"text":text,"voice":voice}).encode(),timeout=30)
                if worker.returncode: raise RuntimeError("Online synthesis failed")
            finally:
                try: os.killpg(worker.pid,signal.SIGKILL)
                except ProcessLookupError: pass
                worker.wait()
            if not pcm or len(pcm)%2 or len(pcm)>24000*2*15:
                raise ValueError("Invalid phrase PCM")
            temp=path.with_suffix(".tmp")
            with wave.open(str(temp),"wb") as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(pcm)
            if not valid_clip(temp): raise ValueError("Invalid phrase WAV")
            temp.replace(path);print(f"[CACHE] SAVED {name}",flush=True)
        except Exception as exc:
            failures+=1;print(f"[CACHE] FAILED {name} {type(exc).__name__}",flush=True)
    return bool(failures)
if __name__=="__main__":sys.exit(main())
