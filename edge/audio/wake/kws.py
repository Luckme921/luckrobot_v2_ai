from __future__ import annotations

from pathlib import Path

import numpy as np
import sherpa_onnx


class WakeKeywordSpotter:
    def __init__(
        self,
        config: dict,
        sample_rate: int,
    ) -> None:
        self.sample_rate = int(
            sample_rate
        )

        self.keyword = str(
            config.get(
                "keyword",
                "LUCKY",
            )
        )

        model_dir = Path(
            config["model_dir"]
        ).expanduser()

        def model_file(
            key: str,
        ) -> Path:
            path = (
                model_dir
                / str(config[key])
            )

            if not path.is_file():
                raise FileNotFoundError(
                    f"KWS file not found: {path}"
                )

            return path

        tokens = model_file(
            "tokens"
        )

        encoder = model_file(
            "encoder"
        )

        decoder = model_file(
            "decoder"
        )

        joiner = model_file(
            "joiner"
        )

        keywords_file = model_file(
            "keywords_file"
        )

        self._spotter = (
            sherpa_onnx.KeywordSpotter(
                tokens=str(tokens),
                encoder=str(encoder),
                decoder=str(decoder),
                joiner=str(joiner),
                keywords_file=str(
                    keywords_file
                ),
                num_threads=int(
                    config.get(
                        "num_threads",
                        1,
                    )
                ),
                sample_rate=self.sample_rate,
                feature_dim=int(
                    config.get(
                        "feature_dim",
                        80,
                    )
                ),
                max_active_paths=int(
                    config.get(
                        "max_active_paths",
                        4,
                    )
                ),
                keywords_score=float(
                    config.get(
                        "keywords_score",
                        1.0,
                    )
                ),
                keywords_threshold=float(
                    config.get(
                        "keywords_threshold",
                        0.25,
                    )
                ),
                num_trailing_blanks=int(
                    config.get(
                        "num_trailing_blanks",
                        1,
                    )
                ),
                provider=str(
                    config.get(
                        "provider",
                        "cpu",
                    )
                ),
            )
        )

    def create_stream(self):
        return self._spotter.create_stream()

    def accept(
        self,
        stream,
        samples: np.ndarray,
    ) -> str | None:
        self._spotter_stream_accept(
            stream,
            samples,
        )

        while self._spotter.is_ready(
            stream
        ):
            self._spotter.decode_stream(
                stream
            )

            result = self._spotter.get_result(
                stream
            )

            if not result:
                continue

            # sherpa-onnx requires reset
            # immediately after a detection.
            self._spotter.reset_stream(
                stream
            )

            return result

        return None

    def _spotter_stream_accept(
        self,
        stream,
        samples: np.ndarray,
    ) -> None:
        stream.accept_waveform(
            self.sample_rate,
            samples,
        )
