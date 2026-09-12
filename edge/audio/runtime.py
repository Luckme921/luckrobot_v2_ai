from __future__ import annotations

import argparse
import subprocess
import time

import numpy as np
import yaml

from edge.audio.asr.sensevoice import (
    SenseVoiceRecognizer,
)
from edge.audio.capture.pulse import (
    PulseCapture,
    PulseCaptureError,
)
from edge.audio.device_resolver.pulse import (
    PulseDeviceNotFound,
    resolve_microphone,
    resolve_speaker,
)
from edge.audio.vad.silero import SileroVad


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def create_vad(
    config: dict,
    sample_rate: int,
) -> SileroVad:
    return SileroVad(
        model=config["model"],
        sample_rate=sample_rate,
        threshold=float(
            config["threshold"]
        ),
        min_silence_duration=float(
            config["min_silence_duration"]
        ),
        min_speech_duration=float(
            config["min_speech_duration"]
        ),
        max_speech_duration=float(
            config["max_speech_duration"]
        ),
        buffer_size_seconds=int(
            config["buffer_size_seconds"]
        ),
        num_threads=int(
            config["num_threads"]
        ),
    )


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

    retry_seconds = float(
        audio_cfg.get(
            "reconnect_interval_seconds",
            1.0,
        )
    )

    print("[INIT] Loading SenseVoice...")

    # Important:
    # ASR is loaded only once and remains resident
    # even when the microphone disconnects.
    asr = SenseVoiceRecognizer(
        model_dir=asr_cfg["model_dir"],
        provider=asr_cfg["provider"],
        num_threads=int(
            asr_cfg["num_threads"]
        ),
        language=asr_cfg["language"],
        use_itn=bool(
            asr_cfg["use_itn"]
        ),
    )

    print("[INIT] SenseVoice ready.")

    state = None

    try:
        while True:
            try:
                print(
                    "[AUDIO] Resolving USB devices..."
                )

                microphone = resolve_microphone(
                    audio_cfg[
                        "microphone"
                    ]["match_any"]
                )

                # Speaker is resolved for system
                # visibility, but ASR input can keep
                # working even if the speaker is absent.
                try:
                    speaker = resolve_speaker(
                        audio_cfg[
                            "speaker"
                        ]["match_any"]
                    )
                except PulseDeviceNotFound:
                    speaker = "<unavailable>"

                print(
                    f"[AUDIO] microphone={microphone}"
                )
                print(
                    f"[AUDIO] speaker={speaker}"
                )

                # Reset VAD whenever a new capture
                # session starts. This prevents audio
                # from the old USB stream leaking into
                # the new session.
                vad = create_vad(
                    vad_cfg,
                    sample_rate,
                )

                capture = PulseCapture(
                    source=microphone,
                    sample_rate=sample_rate,
                    channels=int(
                        audio_cfg["channels"]
                    ),
                    sample_format=(
                        audio_cfg["format"]
                    ),
                )

                print(
                    "[STATE] AUDIO_CONNECTING"
                )

                with capture:
                    state = "AUDIO_OK"

                    print(
                        "[STATE] AUDIO_OK"
                    )
                    print(
                        "[READY] Listening..."
                    )
                    print(
                        "[READY] Press Ctrl+C to stop."
                    )

                    zero_audio_samples = 0
                    zero_audio_limit = int(
                        sample_rate
                        * float(
                            audio_cfg.get(
                                "zero_audio_timeout_seconds",
                                1.0,
                            )
                        )
                    )

                    for pcm in capture.chunks(
                        vad.window_size
                    ):
                        samples = np.frombuffer(
                            pcm,
                            dtype=np.int16,
                        )

                        samples = (
                            samples.astype(
                                np.float32
                            )
                            / 32768.0
                        )

                        if np.any(samples):
                            if (
                                zero_audio_samples
                                >= zero_audio_limit
                                and state
                                == "AUDIO_DEGRADED"
                            ):
                                state = "AUDIO_OK"
                                print(
                                    "[STATE] AUDIO_OK"
                                )
                                print(
                                    "[AUDIO] "
                                    "PCM stream recovered",
                                    flush=True,
                                )

                            zero_audio_samples = 0
                        else:
                            zero_audio_samples += len(
                                samples
                            )

                            if (
                                zero_audio_samples
                                >= zero_audio_limit
                                and state
                                != "AUDIO_DEGRADED"
                            ):
                                state = (
                                    "AUDIO_DEGRADED"
                                )
                                print(
                                    "[STATE] "
                                    "AUDIO_DEGRADED"
                                )
                                print(
                                    "[AUDIO] "
                                    "PCM stream is "
                                    "all-zero",
                                    flush=True,
                                )

                        vad.accept(samples)

                        while vad.has_segment():
                            segment = (
                                vad.pop_segment()
                            )

                            start_sec = (
                                segment.start
                                / sample_rate
                            )

                            duration_sec = (
                                len(
                                    segment.samples
                                )
                                / sample_rate
                            )

                            print(
                                "[VAD] "
                                f"start={start_sec:.2f}s "
                                f"duration={duration_sec:.2f}s",
                                flush=True,
                            )

                            t0 = time.monotonic()

                            text = (
                                asr.transcribe(
                                    segment.samples,
                                    sample_rate,
                                )
                            )

                            elapsed = (
                                time.monotonic()
                                - t0
                            )

                            if not text:
                                print(
                                    "[ASR_EMPTY] "
                                    f"duration={duration_sec:.2f}s "
                                    f"inference={elapsed:.3f}s",
                                    flush=True,
                                )

                            if text:
                                print(
                                    "[ASR] "
                                    f"start="
                                    f"{start_sec:.2f}s "
                                    f"duration="
                                    f"{duration_sec:.2f}s "
                                    f"inference="
                                    f"{elapsed:.3f}s"
                                )

                                print(
                                    f"[TEXT] {text}",
                                    flush=True,
                                )

            except (
                PulseDeviceNotFound,
                PulseCaptureError,
                subprocess.CalledProcessError,
            ) as exc:
                if state != "AUDIO_DEGRADED":
                    print(
                        "[STATE] "
                        "AUDIO_DEGRADED"
                    )

                state = "AUDIO_DEGRADED"

                print(
                    "[AUDIO] "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                print(
                    "[AUDIO] "
                    f"Retrying in "
                    f"{retry_seconds:.1f}s..."
                )

                time.sleep(
                    retry_seconds
                )

    except KeyboardInterrupt:
        print(
            "\n[STOP] Audio runtime stopped."
        )


if __name__ == "__main__":
    main()
