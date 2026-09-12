from __future__ import annotations

import select
import subprocess
from collections.abc import Iterator


class PulseCaptureError(RuntimeError):
    pass


class PulseCapture:
    def __init__(
        self,
        source: str,
        sample_rate: int = 16000,
        channels: int = 1,
        sample_format: str = "s16le",
    ) -> None:
        self.source = source
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_format = sample_format
        self._process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        if self._process is not None:
            return

        command = [
            "parec",
            f"--device={self.source}",
            "--raw",
            "--latency-msec=100",
            "--process-time-msec=20",
            f"--format={self.sample_format}",
            f"--rate={self.sample_rate}",
            f"--channels={self.channels}",
        ]

        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

        if self._process.stdout is None:
            raise PulseCaptureError(
                "Failed to open parec stdout"
            )

        ready, _, _ = select.select(
            [self._process.stdout],
            [],
            [],
            5.0,
        )

        if not ready:
            self.stop()
            raise PulseCaptureError(
                "parec produced no audio "
                "within 5.0 seconds"
            )

        return_code = self._process.poll()

        if return_code is not None:
            self.stop()
            raise PulseCaptureError(
                "parec exited during startup "
                f"with code {return_code}"
            )

    def chunks(
        self,
        samples_per_chunk: int,
    ) -> Iterator[bytes]:
        if (
            self._process is None
            or self._process.stdout is None
        ):
            raise PulseCaptureError(
                "Capture has not been started"
            )

        # PCM16 = 2 bytes per sample.
        bytes_per_chunk = (
            samples_per_chunk
            * self.channels
            * 2
        )

        pending = bytearray()

        while True:
            needed = (
                bytes_per_chunk
                - len(pending)
            )

            data = self._process.stdout.read(
                needed
            )

            if not data:
                return_code = (
                    self._process.poll()
                )

                if return_code is None:
                    raise PulseCaptureError(
                        "parec stream closed unexpectedly"
                    )

                raise PulseCaptureError(
                    "parec exited with "
                    f"code {return_code}"
                )

            pending.extend(data)

            if len(pending) == bytes_per_chunk:
                yield bytes(pending)
                pending.clear()

    def stop(self) -> None:
        if self._process is None:
            return

        process = self._process
        self._process = None

        if process.poll() is None:
            process.terminate()

            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

        if process.stdout:
            process.stdout.close()

    def __enter__(self) -> "PulseCapture":
        self.start()
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ) -> None:
        self.stop()
