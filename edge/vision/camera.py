from __future__ import annotations

from pathlib import Path
import subprocess
import time

from edge.vision.ring_buffer import (
    FileRingBuffer,
    VisionFrame,
)


class CameraError(RuntimeError):
    pass


class GStreamerCameraRing:
    def __init__(
        self,
        *,
        device: str,
        width: int,
        height: int,
        fps: int,
        directory: str | Path,
        max_files: int,
    ) -> None:
        self.device = str(device)
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.directory = Path(
            directory
        )
        self.max_files = int(
            max_files
        )

        if self.width <= 0:
            raise ValueError(
                "width must be > 0"
            )

        if self.height <= 0:
            raise ValueError(
                "height must be > 0"
            )

        if self.fps <= 0:
            raise ValueError(
                "fps must be > 0"
            )

        if self.max_files <= 0:
            raise ValueError(
                "max_files must be > 0"
            )

        self.ring = FileRingBuffer(
            self.directory
        )

        self._process: (
            subprocess.Popen | None
        ) = None

    @property
    def running(
        self,
    ) -> bool:
        return (
            self._process is not None
            and self._process.poll()
            is None
        )

    def _pipeline_command(
        self,
    ) -> list[str]:
        location = str(
            self.directory
            / "frame-%06d.jpg"
        )

        caps = (
            "image/jpeg,"
            f"width={self.width},"
            f"height={self.height},"
            f"framerate={self.fps}/1"
        )

        return [
            "gst-launch-1.0",
            "-q",
            "v4l2src",
            f"device={self.device}",
            "!",
            caps,
            "!",
            "multifilesink",
            f"location={location}",
            f"max-files={self.max_files}",
        ]

    def _clear_existing(
        self,
    ) -> None:
        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        for path in self.directory.glob(
            "frame-*.jpg"
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def start(
        self,
    ) -> None:
        if self.running:
            return

        self._clear_existing()

        try:
            self._process = subprocess.Popen(
                self._pipeline_command(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except (
            FileNotFoundError,
            OSError,
        ) as exc:
            raise CameraError(
                f"Could not start camera: {exc}"
            ) from exc

        time.sleep(
            0.25
        )

        if self._process.poll() is not None:
            _, stderr = (
                self._process
                .communicate()
            )

            self._process = None

            raise CameraError(
                "GStreamer camera exited "
                f"early: {stderr.strip()}"
            )

    def stop(
        self,
    ) -> None:
        process = self._process
        self._process = None

        if process is None:
            return

        if process.poll() is not None:
            return

        process.terminate()

        try:
            process.wait(
                timeout=2.0
            )
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(
                timeout=2.0
            )

    def wait_for_frame(
        self,
        timeout_seconds: float = 3.0,
    ) -> VisionFrame:
        deadline = (
            time.monotonic()
            + float(
                timeout_seconds
            )
        )

        while (
            time.monotonic()
            < deadline
        ):
            frame = (
                self.ring
                .latest_frame()
            )

            if frame is not None:
                return frame

            if (
                self._process
                is not None
                and
                self._process.poll()
                is not None
            ):
                raise CameraError(
                    "Camera process exited "
                    "before first frame"
                )

            time.sleep(
                0.05
            )

        raise CameraError(
            "Timed out waiting "
            "for camera frame"
        )

    def __enter__(
        self,
    ) -> "GStreamerCameraRing":
        self.start()
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ) -> None:
        self.stop()
