from __future__ import annotations

from dataclasses import dataclass
import time

from edge.vision.ring_buffer import (
    VisionFrame,
)


class VisionSelectionError(
    RuntimeError
):
    pass


@dataclass(frozen=True)
class TurnVisionSnapshot:
    anchor_time: float
    latest: VisionFrame | None
    recent: tuple[
        VisionFrame,
        ...
    ]


def _select_evenly(
    frames: list[VisionFrame],
    count: int,
) -> list[VisionFrame]:
    if not frames:
        return []

    count = max(
        1,
        min(
            int(count),
            len(frames),
        ),
    )

    if count == len(frames):
        return list(frames)

    if count == 1:
        return [
            frames[-1]
        ]

    last = len(frames) - 1

    indices = [
        round(
            index
            * last
            / (count - 1)
        )
        for index
        in range(count)
    ]

    return [
        frames[index]
        for index in indices
    ]


def capture_turn_snapshot(
    ring,
    *,
    recent_seconds: float = 6.0,
    recent_count: int = 16,
) -> TurnVisionSnapshot:
    if recent_seconds <= 0:
        raise ValueError(
            "recent_seconds must be > 0"
        )

    if recent_count < 2:
        raise ValueError(
            "recent_count must be >= 2"
        )

    latest = (
        ring.latest_frame()
    )

    recent = list(
        ring.sample_recent(
            recent_seconds,
            recent_count,
        )
    )

    if (
        latest is not None
        and all(
            frame.path
            != latest.path
            for frame in recent
        )
    ):
        recent.append(
            latest
        )

    recent.sort(
        key=lambda frame:
        frame.captured_at
    )

    if latest is not None:
        anchor_time = (
            latest.captured_at
        )
    elif recent:
        anchor_time = (
            recent[-1]
            .captured_at
        )
    else:
        anchor_time = (
            time.time()
        )

    return TurnVisionSnapshot(
        anchor_time=anchor_time,
        latest=latest,
        recent=tuple(
            recent
        ),
    )


def select_turn_snapshot_frames(
    snapshot: TurnVisionSnapshot,
    request,
) -> list[VisionFrame]:
    mode = str(
        request.mode
    ).strip()

    if mode == "latest":
        if snapshot.latest is None:
            raise VisionSelectionError(
                "No turn-aligned current "
                "camera frame is available"
            )

        return [
            snapshot.latest
        ]

    if mode == "recent":
        seconds = max(
            1.0,
            float(
                request.seconds
            ),
        )

        count = max(
            2,
            int(
                request.count
            ),
        )

        cutoff = (
            snapshot.anchor_time
            - seconds
        )

        candidates = [
            frame
            for frame
            in snapshot.recent
            if (
                frame.captured_at
                >= cutoff
            )
        ]

        # The frozen sample is intentionally
        # lightweight. If a very narrow time
        # window contains too few sampled
        # frames, use the most recent frozen
        # samples rather than falling back to
        # live camera time.
        if len(candidates) < 2:
            candidates = list(
                snapshot.recent
            )

        if len(candidates) < 2:
            raise VisionSelectionError(
                "Not enough turn-aligned "
                "recent frames are available"
            )

        return _select_evenly(
            candidates,
            count,
        )

    raise VisionSelectionError(
        "Unsupported vision request "
        f"mode={mode}"
    )


# Kept for standalone camera/ring tests and
# backwards compatibility. Live voice runtime
# should use the turn-aligned snapshot path.
def select_vision_frames(
    ring,
    request,
):
    mode = str(
        request.mode
    ).strip()

    if mode == "latest":
        frame = (
            ring.latest_frame()
        )

        if frame is None:
            raise VisionSelectionError(
                "No current camera frame "
                "is available"
            )

        return [
            frame
        ]

    if mode == "recent":
        frames = (
            ring.sample_recent(
                float(
                    request.seconds
                ),
                int(
                    request.count
                ),
            )
        )

        if len(frames) < 2:
            raise VisionSelectionError(
                "Not enough recent camera "
                "frames are available"
            )

        return frames

    raise VisionSelectionError(
        "Unsupported vision request "
        f"mode={mode}"
    )
