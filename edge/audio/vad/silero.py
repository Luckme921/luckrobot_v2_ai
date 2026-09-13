from __future__ import annotations

import os
from collections import deque

import numpy as np
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
        model = os.path.expanduser(
            model
        )

        if not os.path.isfile(model):
            raise FileNotFoundError(
                model
            )

        config = (
            sherpa_onnx.VadModelConfig()
        )

        config.silero_vad.model = (
            model
        )

        config.silero_vad.threshold = (
            threshold
        )

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

        # Raw PCM history is needed because the
        # VAD segment itself can be too tightly
        # cropped for SenseVoice.
        self._history: deque[
            tuple[int, np.ndarray]
        ] = deque()

        self._accepted_samples = 0

        self._history_limit_samples = int(
            sample_rate
            * buffer_size_seconds
        )

    def accept(
        self,
        samples,
    ) -> None:
        audio = np.asarray(
            samples,
            dtype=np.float32,
        ).reshape(-1)

        if audio.size:
            start = (
                self._accepted_samples
            )

            self._history.append(
                (
                    start,
                    audio.copy(),
                )
            )

            self._accepted_samples += int(
                audio.size
            )

            cutoff = max(
                0,
                self._accepted_samples
                - self._history_limit_samples,
            )

            while self._history:
                chunk_start, chunk = (
                    self._history[0]
                )

                chunk_end = (
                    chunk_start
                    + len(chunk)
                )

                if chunk_end >= cutoff:
                    break

                self._history.popleft()

        self._vad.accept_waveform(
            audio
        )

    def has_segment(
        self,
    ) -> bool:
        return not self._vad.empty()

    def pop_segment(
        self,
    ):
        segment = self._vad.front
        self._vad.pop()
        return segment

    def _history_slice(
        self,
        start: int,
        end: int,
    ) -> np.ndarray:
        parts: list[np.ndarray] = []

        for (
            chunk_start,
            chunk,
        ) in self._history:
            chunk_end = (
                chunk_start
                + len(chunk)
            )

            if chunk_end <= start:
                continue

            if chunk_start >= end:
                break

            left = max(
                start,
                chunk_start,
            ) - chunk_start

            right = min(
                end,
                chunk_end,
            ) - chunk_start

            if right > left:
                parts.append(
                    chunk[
                        left:right
                    ]
                )

        if not parts:
            return np.empty(
                0,
                dtype=np.float32,
            )

        return np.concatenate(
            parts
        )

    def pop_segment_with_context(
        self,
        *,
        pre_seconds: float = 0.30,
        post_seconds: float = 0.20,
    ):
        """
        Return both the original Silero segment and
        raw microphone PCM surrounding that segment.

        SenseVoice benefits strongly from a small
        amount of real acoustic context at both
        boundaries.
        """
        segment = self._vad.front
        self._vad.pop()

        segment_start = int(
            segment.start
        )

        segment_end = (
            segment_start
            + len(segment.samples)
        )

        pre_samples = int(
            self.sample_rate
            * pre_seconds
        )

        post_samples = int(
            self.sample_rate
            * post_seconds
        )

        expanded_start = max(
            0,
            segment_start
            - pre_samples,
        )

        expanded_end = min(
            self._accepted_samples,
            segment_end
            + post_samples,
        )

        expanded = (
            self._history_slice(
                expanded_start,
                expanded_end,
            )
        )

        if expanded.size == 0:
            expanded = np.asarray(
                segment.samples,
                dtype=np.float32,
            ).copy()

        return (
            segment,
            expanded,
        )
