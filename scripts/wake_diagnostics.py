"""Explicit recording and offline KWS replay. Never sends audio to the cloud."""
import argparse
import json
from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read_wav(path):
    import numpy as np
    with wave.open(str(path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError("Expected mono 16-bit PCM WAV at 16000 Hz")
        if wav.getnframes() > 16000 * 600:
            raise ValueError("Clip exceeds ten minutes")
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype("float32") / 32768.0


def record(config, output, seconds):
    from edge.audio.capture.pulse import PulseCapture
    from edge.audio.device_resolver.pulse import resolve_microphone
    audio = config["audio"]
    mic = audio["microphone"]
    capture = PulseCapture(resolve_microphone(mic["match_any"]), sample_rate=16000,
                           input_channels=mic.get("input_channels", 1),
                           selected_channel=mic.get("selected_channel"))
    output.parent.mkdir(parents=True, exist_ok=True)
    # Never silently replace an earlier labelled sample.
    with output.open("xb") as destination:
        with wave.open(destination, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            remaining = round(seconds * 16000) * 2
            print(f"RECORDING seconds={seconds} output={output}", flush=True)
            try:
                capture.start()
                for pcm in capture.chunks(320):
                    chunk = pcm[:remaining]
                    wav.writeframesraw(chunk)
                    remaining -= len(chunk)
                    if remaining <= 0:
                        break
            finally:
                capture.stop()
    print("RECORDING_DONE", flush=True)


def evaluate(config, paths, thresholds, keywords_file=None):
    import numpy as np
    from edge.audio.wake.kws import WakeKeywordSpotter
    settings = dict(config["interaction"]["wake"])
    if keywords_file:
        settings["keywords_file"] = str(Path(keywords_file).resolve())
    for threshold in thresholds:
        settings["keywords_threshold"] = threshold
        kws = WakeKeywordSpotter(settings, 16000)
        for path in paths:
            samples = read_wav(path)
            # Final blank frames drain the streaming decoder.
            samples = np.concatenate((samples, np.zeros(16000, dtype="float32")))
            stream = kws.create_stream()
            hits = []
            for offset in range(0, len(samples), 320):
                keyword = kws.accept(stream, samples[offset:offset+320])
                if keyword:
                    hits.append({"keyword": keyword, "detected_at_seconds": round((offset+320)/16000, 2)})
            print(json.dumps({"file": str(path), "threshold": threshold, "hits": hits}, ensure_ascii=False))


def main():
    import yaml
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "configs/audio.yaml"))
    sub = parser.add_subparsers(dest="mode", required=True)
    capture = sub.add_parser("record")
    capture.add_argument("--seconds", type=float, default=15)
    capture.add_argument("--output", required=True, type=Path)
    replay = sub.add_parser("evaluate")
    replay.add_argument("paths", nargs="+", type=Path)
    replay.add_argument("--thresholds", nargs="+", type=float, default=[0.2, 0.25, 0.35])
    replay.add_argument("--keywords-file")
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if args.mode == "record":
        if not 1 <= args.seconds <= 600:
            parser.error("seconds must be between 1 and 600")
        record(config, args.output.expanduser().resolve(), args.seconds)
    else:
        if any(not 0 < value <= 1 for value in args.thresholds):
            parser.error("thresholds must be between 0 and 1")
        evaluate(config, args.paths, args.thresholds, args.keywords_file)


if __name__ == "__main__":
    main()
