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
    split_for_speech,
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

        self.max_chunk_chars = max(
            8,
            int(
                config.get(
                    "max_chunk_chars",
                    24,
                )
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
        text = text.strip()
        sink = sink.strip()

        if not text:
            raise TtsError(
                "TTS text is empty"
            )

        if not sink:
            raise TtsError(
                "TTS sink is empty"
            )

        chunks = split_for_speech(
            text,
            max_chars=(
                self.max_chunk_chars
            ),
        )

        if not chunks:
            raise TtsError(
                "TTS text became empty "
                "after normalization"
            )

        self._prepare_sink(
            sink
        )

        work_queue: queue.Queue[
            tuple[str, object]
        ] = queue.Queue()

        def producer() -> None:
            try:
                for chunk_text in chunks:
                    generated = (
                        self._generate(
                            chunk_text
                        )
                    )

                    work_queue.put(
                        (
                            "audio",
                            generated,
                        )
                    )

            except Exception as exc:
                work_queue.put(
                    (
                        "error",
                        exc,
                    )
                )

            finally:
                work_queue.put(
                    (
                        "done",
                        None,
                    )
                )

        start = time.monotonic()

        worker = threading.Thread(
            target=producer,
            name="luckrobot-tts",
            daemon=True,
        )

        worker.start()

        first_audio_latency = None
        generation_seconds = 0.0
        audio_seconds = 0.0
        sample_rate = 0
        played_chunks = 0

        while True:
            kind, payload = (
                work_queue.get()
            )

            if kind == "done":
                break

            if kind == "error":
                if isinstance(
                    payload,
                    TtsError,
                ):
                    raise payload

                raise TtsError(
                    "TTS producer failed: "
                    f"{payload}"
                )

            generated = payload

            if not isinstance(
                generated,
                _GeneratedChunk,
            ):
                raise TtsError(
                    "Invalid generated "
                    "TTS chunk"
                )

            if first_audio_latency is None:
                first_audio_latency = (
                    time.monotonic()
                    - start
                )

            generation_seconds += (
                generated
                .generation_seconds
            )

            chunk_audio_seconds = (
                len(
                    generated.samples
                )
                / generated.sample_rate
            )

            audio_seconds += (
                chunk_audio_seconds
            )

            sample_rate = (
                generated.sample_rate
            )

            self._play_chunk(
                generated,
                sink,
            )

            played_chunks += 1

        worker.join()

        wall_seconds = (
            time.monotonic()
            - start
        )

        return TtsResult(
            generation_seconds=(
                generation_seconds
            ),
            audio_seconds=(
                audio_seconds
            ),
            sample_rate=(
                sample_rate
            ),
            first_audio_latency_seconds=(
                first_audio_latency
                if first_audio_latency
                is not None
                else wall_seconds
            ),
            wall_seconds=(
                wall_seconds
            ),
            chunks=(
                played_chunks
            ),
        )
