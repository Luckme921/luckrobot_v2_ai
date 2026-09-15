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
        input_channels: int | None = None,
        selected_channel: int | None = None,
    ) -> None:
        self.source = source
        self.sample_rate = sample_rate

        # Number of channels delivered to the
        # rest of LuckRobot.
        self.channels = channels

        # Number of channels requested from the
        # physical/PulseAudio capture device.
        self.input_channels = (
            channels
            if input_channels is None
            else int(input_channels)
        )

        self.selected_channel = (
            selected_channel
        )

        self.sample_format = sample_format
        self._process: subprocess.Popen[bytes] | None = None

        if self.channels <= 0:
            raise ValueError(
                "channels must be positive"
            )

        if self.input_channels <= 0:
            raise ValueError(
                "input_channels must be positive"
            )

        if (
            self.selected_channel is None
            and self.input_channels != self.channels
        ):
            raise ValueError(
                "input_channels must match channels "
                "when selected_channel is not set"
            )

        if self.selected_channel is not None:
            if self.sample_format != "s16le":
                raise ValueError(
                    "channel selection currently "
                    "requires s16le"
                )

            if self.channels != 1:
                raise ValueError(
                    "selected_channel requires "
                    "mono output"
                )

            if not (
                0
                <= self.selected_channel
                < self.input_channels
            ):
                raise ValueError(
                    "selected_channel is outside "
                    "input channel range"
                )

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
            f"--channels={self.input_channels}",
        ]

        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            start_new_session=True,
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
        #
        # Read complete frames from the physical
        # input first. If selected_channel is set,
        # one logical channel is then extracted
        # before yielding to KWS/VAD/ASR.
        input_bytes_per_chunk = (
            samples_per_chunk
            * self.input_channels
            * 2
        )

        pending = bytearray()

        while True:
            needed = (
                input_bytes_per_chunk
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

            if (
                len(pending)
                == input_bytes_per_chunk
            ):
                raw = bytes(
                    pending
                )

                pending.clear()

                if (
                    self.selected_channel
                    is None
                ):
                    yield raw
                    continue

                # Interleaved S16_LE:
                #
                # ch0 ch1 ch0 ch1 ...
                #
                # XVF3800 default USB routing uses
                # channel 1 (Right) as its ASR
                # auto-selected-beam output.
                frame_bytes = (
                    self.input_channels
                    * 2
                )

                offset = (
                    self.selected_channel
                    * 2
                )

                selected = bytearray(
                    samples_per_chunk
                    * 2
                )

                out = 0

                for frame in range(
                    0,
                    len(raw),
                    frame_bytes,
                ):
                    selected[
                        out:out + 2
                    ] = raw[
                        frame + offset:
                        frame + offset + 2
                    ]

                    out += 2

                yield bytes(
                    selected
                )

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
