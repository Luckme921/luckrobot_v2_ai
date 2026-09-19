"""Isolated TTS comparison. Fixed public test text only; never plays audio."""
import argparse
import asyncio
import importlib.metadata
import json
from pathlib import Path
import time
import wave

CASES = [
    ("short", "好的，我帮你查一下。"),
    ("chat", "今天过得怎么样？如果累了，就先休息一会儿。我们慢慢来，不着急。"),
    ("music", "找到三首歌曲。第一首，稻香，周杰伦。第二首，晴天，周杰伦。第三首，七里香，周杰伦。你想听哪一首？"),
    ("mixed", "我是 Lucky。现在是下午三点二十五分，室内温度二十六点五摄氏度，电量百分之八十。"),
]

def write_row(path, row):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(row, ensure_ascii=False), flush=True)

def piper_test(args, report):
    from piper import PiperVoice
    started = time.monotonic()
    voice = PiperVoice.load(args.model)
    write_row(report, dict(engine="piper", event="load", seconds=time.monotonic()-started,
                           version=importlib.metadata.version("piper-tts")))
    for run in range(args.runs):
        for name, text in CASES:
            row = dict(engine="piper", case=name, run=run+1, text=text)
            started = time.monotonic(); first = None; frames = 0; chunks = 0
            path = args.output / f"piper-{name}-{run+1}.wav"
            try:
                with wave.open(str(path), "wb") as wav:
                    for chunk in voice.synthesize(text):
                        now = time.monotonic()
                        if first is None: first = now-started
                        if chunks == 0:
                            wav.setframerate(chunk.sample_rate)
                            wav.setsampwidth(chunk.sample_width)
                            wav.setnchannels(chunk.sample_channels)
                        data = chunk.audio_int16_bytes
                        frames += len(data)/(chunk.sample_width*chunk.sample_channels)
                        wav.writeframesraw(data); chunks += 1
                duration = frames/chunk.sample_rate if chunks else 0
                elapsed = time.monotonic()-started
                if not chunks: raise ValueError("Empty audio")
                row.update(ok=True, first_audio_seconds=first, total_seconds=elapsed,
                           audio_seconds=duration, rtf=elapsed/duration, chunks=chunks, file=path.name)
            except Exception as exc:
                path.unlink(missing_ok=True)
                row.update(ok=False, error=type(exc).__name__, total_seconds=time.monotonic()-started)
            write_row(report,row)

def kokoro_test(args, report):
    import yaml
    import sherpa_onnx
    from edge.audio.tts.kokoro import KokoroTts
    from edge.audio.tts.text import normalize_for_speech
    config = yaml.safe_load(Path("configs/audio.yaml").read_text())["tts"]
    started = time.monotonic(); tts = KokoroTts(config)
    write_row(report, dict(engine="kokoro", event="load", seconds=time.monotonic()-started,
                           version=importlib.metadata.version("sherpa-onnx")))
    for run in range(args.runs):
        for name,text in CASES:
            row=dict(engine="kokoro",case=name,run=run+1,text=text)
            path=args.output/f"kokoro-{name}-{run+1}.wav"
            first=None; chunks=0; started=time.monotonic()
            def on_audio(samples, progress):
                nonlocal first,chunks
                if len(samples):
                    if first is None: first=time.monotonic()-started
                    chunks+=1
                return 1
            try:
                cfg=sherpa_onnx.GenerationConfig()
                cfg.sid=tts.speaker_id; cfg.speed=tts.speed; cfg.silence_scale=tts.silence_scale
                audio=tts._tts.generate(normalize_for_speech(text),cfg,on_audio)
                elapsed=time.monotonic()-started
                duration=len(audio.samples)/audio.sample_rate
                tts._write_wav(path,audio.samples,audio.sample_rate)
                row.update(ok=True,first_audio_seconds=first,total_seconds=elapsed,
                           audio_seconds=duration,rtf=elapsed/duration,chunks=chunks,file=path.name)
            except Exception as exc:
                path.unlink(missing_ok=True)
                row.update(ok=False,error=type(exc).__name__,total_seconds=time.monotonic()-started)
            write_row(report,row)

async def edge_test(args, report):
    import edge_tts
    for voice in args.voices:
        for run in range(args.runs):
            for name,text in CASES:
                row=dict(engine="edge", voice=voice, case=name, run=run+1, text=text,
                         version=importlib.metadata.version("edge-tts"))
                path=args.output/f"edge-{voice}-{name}-{run+1}.mp3"
                started=time.monotonic(); first=None; size=0; chunks=0
                async def collect():
                    nonlocal first,size,chunks
                    with path.open("wb") as f:
                        async for event in edge_tts.Communicate(text,voice).stream():
                            if event["type"] != "audio": continue
                            if first is None: first=time.monotonic()-started
                            f.write(event["data"]); size+=len(event["data"]); chunks+=1
                    if not size: raise ValueError("Empty audio")
                try:
                    await asyncio.wait_for(collect(),timeout=25)
                    row.update(ok=True, first_audio_seconds=first,total_seconds=time.monotonic()-started,
                               bytes=size,chunks=chunks,file=path.name)
                except Exception as exc:
                    path.unlink(missing_ok=True)
                    row.update(ok=False,error=type(exc).__name__,total_seconds=time.monotonic()-started)
                write_row(report,row)

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine",choices=["piper","edge","kokoro"],required=True)
    parser.add_argument("--model",default="private/tts-eval/models/zh_CN-huayan-medium.onnx")
    parser.add_argument("--output",type=Path,default=Path("private/tts-eval/samples"))
    parser.add_argument("--runs",type=int,default=3)
    parser.add_argument("--voices",nargs="+",default=["zh-CN-XiaoxiaoNeural","zh-CN-YunxiNeural"])
    args=parser.parse_args()
    if not 1<=args.runs<=10: parser.error("runs must be 1..10")
    args.output.mkdir(parents=True,exist_ok=True)
    report=args.output/(args.engine+"-results.jsonl")
    if args.engine=="piper": piper_test(args,report)
    elif args.engine=="kokoro": kokoro_test(args,report)
    else: asyncio.run(edge_test(args,report))
