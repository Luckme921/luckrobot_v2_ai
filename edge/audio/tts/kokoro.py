from __future__ import annotations

import queue
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sherpa_onnx

from edge.audio.tts.text import (
    normalize_for_speech,
)


class TtsError(RuntimeError):
    pass


@dataclass(frozen=True)
class TtsResult:
    generation_seconds: float
    audio_seconds: float
    sample_rate: int
    first_audio_latency_seconds: float
    wall_seconds: float
    chunks: int


@dataclass(frozen=True)
class _GeneratedChunk:
    samples: np.ndarray
    sample_rate: int
    generation_seconds: float


class KokoroTts:
    def __init__(
        self,
        config: dict,
    ) -> None:
        self.model_dir = Path(
            str(config["model_dir"])
        ).expanduser().resolve()

        self.speaker_id = int(
            config.get(
                "speaker_id",
                50,
            )
        )

        self.num_threads = int(
            config.get(
                "num_threads",
                6,
            )
        )

        self.speed = float(
            config.get(
                "speed",
                1.0,
            )
        )

        self.silence_scale = float(
            config.get(
                "silence_scale",
                0.2,
            )
        )

        self.volume_percent = max(
            0,
            min(
                100,
                int(
                    config.get(
                        "volume_percent",
                        80,
                    )
                ),
            ),
        )

        required = [
            "model.onnx",
            "voices.bin",
            "tokens.txt",
            "espeak-ng-data",
            "lexicon-us-en.txt",
            "lexicon-zh.txt",
            "date-zh.fst",
            "phone-zh.fst",
            "number-zh.fst",
        ]

        for name in required:
            path = (
                self.model_dir
                / name
            )

            if not path.exists():
                raise TtsError(
                    "Missing Kokoro resource: "
                    f"{path}"
                )

        kokoro_config = (
            sherpa_onnx
            .OfflineTtsKokoroModelConfig(
                model=str(
                    self.model_dir
                    / "model.onnx"
                ),
                voices=str(
                    self.model_dir
                    / "voices.bin"
                ),
                tokens=str(
                    self.model_dir
                    / "tokens.txt"
                ),
                data_dir=str(
                    self.model_dir
                    / "espeak-ng-data"
                ),
                lexicon=(
                    f"{self.model_dir / 'lexicon-us-en.txt'},"
                    f"{self.model_dir / 'lexicon-zh.txt'}"
                ),
            )
        )

        model_config = (
            sherpa_onnx
            .OfflineTtsModelConfig(
                kokoro=kokoro_config,
                provider="cpu",
                num_threads=(
                    self.num_threads
                ),
                debug=False,
            )
        )

        tts_config = (
            sherpa_onnx
            .OfflineTtsConfig(
                model=model_config,
                rule_fsts=(
                    f"{self.model_dir / 'date-zh.fst'},"
                    f"{self.model_dir / 'phone-zh.fst'},"
                    f"{self.model_dir / 'number-zh.fst'}"
                ),
                max_num_sentences=1,
            )
        )

        if not tts_config.validate():
            raise TtsError(
                "Kokoro TTS config "
                "validation failed"
            )

        self._tts = (
            sherpa_onnx
            .OfflineTts(
                tts_config
            )
        )

    def _generate(
        self,
        text: str,
    ) -> _GeneratedChunk:
        generation_config = (
            sherpa_onnx
            .GenerationConfig()
        )

        generation_config.sid = (
            self.speaker_id
        )

        generation_config.speed = (
            self.speed
        )

        generation_config.silence_scale = (
            self.silence_scale
        )

        try:
            start = time.monotonic()

            audio = self._tts.generate(
                text,
                generation_config,
            )

            elapsed = (
                time.monotonic()
                - start
            )

        except Exception as exc:
            raise TtsError(
                "Kokoro synthesis failed: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ) from exc

        if (
            audio.sample_rate <= 0
            or len(audio.samples) == 0
        ):
            raise TtsError(
                "Kokoro returned "
                "empty audio"
            )

        return _GeneratedChunk(
            samples=np.asarray(
                audio.samples,
                dtype=np.float32,
            ).copy(),
            sample_rate=int(
                audio.sample_rate
            ),
            generation_seconds=(
                elapsed
            ),
        )

    @staticmethod
    def _write_wav(
        path: Path,
        samples: np.ndarray,
        sample_rate: int,
    ) -> None:
        pcm = (
            np.clip(
                samples,
                -1.0,
                1.0,
            )
            * 32767.0
        ).astype(np.int16)

        with wave.open(
            str(path),
            "wb",
        ) as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(
                sample_rate
            )
            wav.writeframes(
                pcm.tobytes()
            )

    def _prepare_sink(
        self,
        sink: str,
    ) -> None:
        try:
            subprocess.run(
                [
                    "pactl",
                    "set-sink-mute",
                    sink,
                    "0",
                ],
                check=True,
            )

            subprocess.run(
                [
                    "pactl",
                    "set-sink-volume",
                    sink,
                    (
                        f"{self.volume_percent}%"
                    ),
                ],
                check=True,
            )

        except (
            OSError,
            subprocess.CalledProcessError,
        ) as exc:
            raise TtsError(
                "TTS sink setup failed: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ) from exc

    def _play_chunk(
        self,
        chunk: _GeneratedChunk,
        sink: str,
    ) -> None:
        temp_path = None

        try:
            with (
                tempfile
                .NamedTemporaryFile(
                    prefix="luckrobot_tts_",
                    suffix=".wav",
                    delete=False,
                )
            ) as tmp:
                temp_path = Path(
                    tmp.name
                )

            self._write_wav(
                temp_path,
                chunk.samples,
                chunk.sample_rate,
            )

            subprocess.run(
                [
                    "paplay",
                    f"--device={sink}",
                    str(temp_path),
                ],
                check=True,
            )

        except (
            OSError,
            subprocess.CalledProcessError,
        ) as exc:
            raise TtsError(
                "TTS playback failed: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ) from exc

        finally:
            if temp_path is not None:
                temp_path.unlink(
                    missing_ok=True
                )

    def speak(
        self,
        text: str,
        sink: str,
    ) -> TtsResult:
        # Keep the reply as one logical utterance.
        # Kokoro sees the complete text so its
        # punctuation/prosody stay natural.
        text = normalize_for_speech(
            text
        )

        sink = sink.strip()

        if not text:
            raise TtsError(
                "TTS text is empty"
            )

        if not sink:
            raise TtsError(
                "TTS sink is empty"
            )

        self._prepare_sink(
            sink
        )

        sample_rate = int(
            self._tts.sample_rate
        )

        if sample_rate <= 0:
            raise TtsError(
                "Invalid TTS sample rate"
            )

        try:
            player = subprocess.Popen(
                [
                    "pacat",
                    "--playback",
                    "--raw",
                    f"--device={sink}",
                    "--format=s16le",
                    f"--rate={sample_rate}",
                    "--channels=1",
                ],
                stdin=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as exc:
            raise TtsError(
                "Unable to start pacat: "
                f"{exc}"
            ) from exc

        if player.stdin is None:
            player.terminate()

            raise TtsError(
                "pacat stdin unavailable"
            )

        audio_queue: queue.Queue[
            bytes | None
        ] = queue.Queue()

        playback_errors: list[
            BaseException
        ] = []

        def playback_worker() -> None:
            try:
                while True:
                    data = audio_queue.get()

                    if data is None:
                        break

                    player.stdin.write(
                        data
                    )

            except BaseException as exc:
                playback_errors.append(
                    exc
                )

            finally:
                try:
                    player.stdin.close()
                except Exception:
                    pass

        worker = threading.Thread(
            target=playback_worker,
            name="luckrobot-tts-playback",
            daemon=True,
        )

        worker.start()

        generation_config = (
            sherpa_onnx.GenerationConfig()
        )

        generation_config.sid = (
            self.speaker_id
        )

        generation_config.speed = (
            self.speed
        )

        generation_config.silence_scale = (
            self.silence_scale
        )

        started = time.monotonic()

        first_audio_latency = None
        callback_batches = 0

        def on_audio(
            samples,
            progress,
        ):
            nonlocal first_audio_latency
            nonlocal callback_batches

            array = np.asarray(
                samples,
                dtype=np.float32,
            ).reshape(-1)

            if len(array) == 0:
                return 1

            if first_audio_latency is None:
                first_audio_latency = (
                    time.monotonic()
                    - started
                )

            pcm = (
                np.clip(
                    array,
                    -1.0,
                    1.0,
                )
                * 32767.0
            ).astype(
                np.int16
            )

            audio_queue.put(
                pcm.tobytes()
            )

            callback_batches += 1

            # Verified on sherpa-onnx 1.13.7:
            # 1 = continue generation
            # 0 = stop generation early
            return 1

        try:
            audio = self._tts.generate(
                text,
                generation_config,
                on_audio,
            )

            generation_seconds = (
                time.monotonic()
                - started
            )

            # Defensive fallback:
            # if a backend returns audio but never
            # invokes the callback, play the returned
            # complete waveform once.
            if (
                callback_batches == 0
                and len(audio.samples) > 0
            ):
                array = np.asarray(
                    audio.samples,
                    dtype=np.float32,
                ).reshape(-1)

                if first_audio_latency is None:
                    first_audio_latency = (
                        time.monotonic()
                        - started
                    )

                pcm = (
                    np.clip(
                        array,
                        -1.0,
                        1.0,
                    )
                    * 32767.0
                ).astype(
                    np.int16
                )

                audio_queue.put(
                    pcm.tobytes()
                )

        except Exception as exc:
            audio_queue.put(
                None
            )

            worker.join(
                timeout=2.0
            )

            try:
                player.terminate()
                player.wait(
                    timeout=2.0
                )
            except Exception:
                pass

            raise TtsError(
                "Kokoro streaming synthesis "
                "failed: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ) from exc

        audio_queue.put(
            None
        )

        worker.join()

        return_code = player.wait()

        if playback_errors:
            raise TtsError(
                "TTS streaming playback "
                "failed: "
                f"{playback_errors[0]}"
            )

        if return_code != 0:
            raise TtsError(
                "pacat exited with code "
                f"{return_code}"
            )

        if (
            audio.sample_rate <= 0
            or len(audio.samples) == 0
        ):
            raise TtsError(
                "Kokoro returned empty audio"
            )

        wall_seconds = (
            time.monotonic()
            - started
        )

        audio_seconds = (
            len(audio.samples)
            / audio.sample_rate
        )

        return TtsResult(
            generation_seconds=(
                generation_seconds
            ),
            audio_seconds=(
                audio_seconds
            ),
            sample_rate=int(
                audio.sample_rate
            ),
            first_audio_latency_seconds=(
                first_audio_latency
                if first_audio_latency
                is not None
                else generation_seconds
            ),
            wall_seconds=(
                wall_seconds
            ),

            # One logical utterance.
            # Internal callback batches are not
            # application-level text chunks.
            chunks=1,
        )
