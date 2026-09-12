from __future__ import annotations

import argparse
import time

import numpy as np
import yaml

from edge.audio.asr.sensevoice import (
    SenseVoiceRecognizer,
)
from edge.audio.capture.pulse import PulseCapture
from edge.audio.device_resolver.pulse import (
    resolve_microphone,
    resolve_speaker,
)
from edge.audio.vad.silero import SileroVad


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/audio.yaml",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    audio_cfg = config["audio"]
    vad_cfg = config["vad"]
    asr_cfg = config["asr"]

    sample_rate = int(
        audio_cfg["sample_rate"]
    )

    print("[INIT] Resolving USB audio devices...")

    microphone = resolve_microphone(
        audio_cfg["microphone"]["match_any"]
    )

    speaker = resolve_speaker(
        audio_cfg["speaker"]["match_any"]
    )

    print(f"[AUDIO] microphone={microphone}")
    print(f"[AUDIO] speaker={speaker}")

    print("[INIT] Loading Silero VAD...")

    vad = SileroVad(
        model=vad_cfg["model"],
        sample_rate=sample_rate,
        threshold=float(vad_cfg["threshold"]),
        min_silence_duration=float(
            vad_cfg["min_silence_duration"]
        ),
        min_speech_duration=float(
            vad_cfg["min_speech_duration"]
        ),
        max_speech_duration=float(
            vad_cfg["max_speech_duration"]
        ),
        buffer_size_seconds=int(
            vad_cfg["buffer_size_seconds"]
        ),
        num_threads=int(
            vad_cfg["num_threads"]
        ),
    )

    print("[INIT] Loading SenseVoice...")

    asr = SenseVoiceRecognizer(
        model_dir=asr_cfg["model_dir"],
        provider=asr_cfg["provider"],
        num_threads=int(
            asr_cfg["num_threads"]
        ),
        language=asr_cfg["language"],
        use_itn=bool(asr_cfg["use_itn"]),
    )

    print("[READY] Listening...")
    print("[READY] Press Ctrl+C to stop.")

    capture = PulseCapture(
        source=microphone,
        sample_rate=sample_rate,
        channels=int(audio_cfg["channels"]),
        sample_format=audio_cfg["format"],
    )

    try:
        with capture:
            for pcm in capture.chunks(
                vad.window_size
            ):
                samples = np.frombuffer(
                    pcm,
                    dtype=np.int16,
                )

                samples = (
                    samples.astype(np.float32)
                    / 32768.0
                )

                vad.accept(samples)

                while vad.has_segment():
                    segment = vad.pop_segment()

                    start_sec = (
                        segment.start
                        / sample_rate
                    )

                    duration_sec = (
                        len(segment.samples)
                        / sample_rate
                    )

                    t0 = time.monotonic()

                    text = asr.transcribe(
                        segment.samples,
                        sample_rate,
                    )

                    elapsed = (
                        time.monotonic() - t0
                    )

                    if text:
                        print(
                            "[ASR] "
                            f"start={start_sec:.2f}s "
                            f"duration={duration_sec:.2f}s "
                            f"inference={elapsed:.3f}s"
                        )
                        print(
                            f"[TEXT] {text}",
                            flush=True,
                        )

    except KeyboardInterrupt:
        print("\n[STOP] Audio runtime stopped.")


if __name__ == "__main__":
    main()
