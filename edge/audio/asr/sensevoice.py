from __future__ import annotations

import os

import sherpa_onnx


class SenseVoiceRecognizer:
    def __init__(
        self,
        model_dir: str,
        provider: str = "cpu",
        num_threads: int = 4,
        language: str = "zh",
        use_itn: bool = True,
    ) -> None:
        model_dir = os.path.expanduser(model_dir)

        model = os.path.join(
            model_dir,
            "model.int8.onnx",
        )
        tokens = os.path.join(
            model_dir,
            "tokens.txt",
        )

        if not os.path.isfile(model):
            raise FileNotFoundError(model)

        if not os.path.isfile(tokens):
            raise FileNotFoundError(tokens)

        self._recognizer = (
            sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=model,
                tokens=tokens,
                num_threads=num_threads,
                provider=provider,
                language=language,
                use_itn=use_itn,
                debug=False,
            )
        )

    def transcribe(
        self,
        samples,
        sample_rate: int = 16000,
    ) -> str:
        stream = self._recognizer.create_stream()

        stream.accept_waveform(
            sample_rate,
            samples,
        )

        self._recognizer.decode_stream(stream)

        return stream.result.text.strip()
