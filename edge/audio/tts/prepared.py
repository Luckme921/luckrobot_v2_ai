"""In-memory PCM prepared ahead of ordered playback."""
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PreparedTtsAudio:
    pcm: bytes
    sample_rate: int
    generation_seconds: float
    first_audio_latency_seconds: float
    leading_silence_seconds: float
    trailing_silence_seconds: float

    @property
    def audio_seconds(self):
        return len(self.pcm) / (self.sample_rate * 2)


def prepared_audio(pcm, sample_rate, generation_seconds, first_audio_latency_seconds):
    samples = np.frombuffer(pcm, dtype="<i2")
    active = np.flatnonzero(np.abs(samples.astype(np.int32)) > 200)
    if len(active):
        leading = int(active[0]) / sample_rate
        trailing = (len(samples) - int(active[-1]) - 1) / sample_rate
    else:
        leading = trailing = len(samples) / sample_rate
    return PreparedTtsAudio(
        pcm=pcm,
        sample_rate=sample_rate,
        generation_seconds=generation_seconds,
        first_audio_latency_seconds=first_audio_latency_seconds,
        leading_silence_seconds=leading,
        trailing_silence_seconds=trailing,
    )
