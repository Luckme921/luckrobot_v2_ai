from __future__ import annotations

from pathlib import Path
import sys
import time

import yaml


ROOT = Path(
    __file__
).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from edge.vision.camera import (
    GStreamerCameraRing,
)

CONFIG = (
    ROOT
    / "configs"
    / "vision.yaml"
)


def main() -> None:
    config = yaml.safe_load(
        CONFIG.read_text(
            encoding="utf-8"
        )
    )

    vision = config["vision"]
    camera_cfg = vision["camera"]
    ring_cfg = vision["ring_buffer"]

    camera = GStreamerCameraRing(
        device=camera_cfg["device"],
        width=camera_cfg["width"],
        height=camera_cfg["height"],
        fps=camera_cfg["fps"],
        directory=ring_cfg["directory"],
        max_files=ring_cfg[
            "max_files"
        ],
    )

    print(
        "[VISION] STARTING",
        flush=True,
    )

    with camera:
        first = (
            camera.wait_for_frame(
                4.0
            )
        )

        print(
            "[VISION] FIRST_FRAME "
            f"bytes="
            f"{len(first.jpeg_bytes)}",
            flush=True,
        )

        time.sleep(
            5.5
        )

        latest = (
            camera.ring
            .latest_frame()
        )

        two_seconds_ago = (
            camera.ring
            .frame_ago(
                2.0
            )
        )

        recent = (
            camera.ring
            .sample_recent(
                5.0,
                5,
            )
        )

        files = list(
            Path(
                ring_cfg["directory"]
            ).glob(
                "frame-*.jpg"
            )
        )

        print(
            "[VISION] BUFFER_FILES="
            f"{len(files)}"
        )

        print(
            "[VISION] LATEST="
            f"{latest.path.name if latest else None}"
        )

        print(
            "[VISION] AGO_2S="
            f"{two_seconds_ago.path.name if two_seconds_ago else None}"
        )

        print(
            "[VISION] RECENT_SAMPLE="
            + ",".join(
                frame.path.name
                for frame in recent
            )
        )

        print(
            "[VISION] RECENT_COUNT="
            f"{len(recent)}"
        )

    print(
        "[VISION] STOPPED",
        flush=True,
    )


if __name__ == "__main__":
    main()
