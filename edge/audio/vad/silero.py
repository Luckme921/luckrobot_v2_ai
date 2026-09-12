from __future__ import annotations

import os

import sherpa_onnx


class SileroVad:
    def __init__(
        self,
        model: str,
        sample_rate: int = 16000,
        threshold: float = 0.5,
        min_silence_duration: float = 0.40,
        min_speech_duration: float = 0.25,
        max_speech_duration: float = 20.0,
        buffer_size_seconds: int = 30,
        num_threads: int = 1,
    ) -> None:
        model = os.path.expanduser(model)

        if not os.path.isfile(model):
            raise FileNotFoundError(model)

        config = sherpa_onnx.VadModelConfig()

        config.silero_vad.model = model
        config.silero_vad.threshold = threshold
        config.silero_vad.min_silence_duration = (
            min_silence_duration
        )
        config.silero_vad.min_speech_duration = (
            min_speech_duration
        )
        config.silero_vad.max_speech_duration = (
            max_speech_duration
        )

        config.sample_rate = sample_rate
        config.num_threads = num_threads
        config.provider = "cpu"

        self.sample_rate = sample_rate
        self.window_size = (
            config.silero_vad.window_size
        )

        self._vad = (
            sherpa_onnx.VoiceActivityDetector(
                config,
                buffer_size_in_seconds=(
                    buffer_size_seconds
                ),
            )
        )

    def accept(self, samples) -> None:
        self._vad.accept_waveform(samples)

    def has_segment(self) -> bool:
        return not self._vad.empty()

    def pop_segment(self):
        segment = self._vad.front
        self._vad.pop()
        return segment
