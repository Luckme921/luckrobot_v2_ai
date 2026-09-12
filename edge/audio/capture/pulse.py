from __future__ import annotations

import subprocess
from collections.abc import Iterator


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
            f"--format={self.sample_format}",
            f"--rate={self.sample_rate}",
            f"--channels={self.channels}",
        ]

        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if self._process.stdout is None:
            raise RuntimeError("Failed to open parec stdout")

    def chunks(self, samples_per_chunk: int) -> Iterator[bytes]:
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("Capture has not been started")

        # PCM16 = 2 bytes/sample.
        bytes_per_chunk = (
            samples_per_chunk
            * self.channels
            * 2
        )

        pending = bytearray()

        while True:
            needed = bytes_per_chunk - len(pending)
            data = self._process.stdout.read(needed)

            if not data:
                return

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

        if process.stderr:
            process.stderr.close()

    def __enter__(self) -> "PulseCapture":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
