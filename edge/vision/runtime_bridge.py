from __future__ import annotations


class VisionSelectionError(
    RuntimeError
):
    pass


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
