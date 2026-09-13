#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import argparse
import sys
import time


REPO_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(REPO_ROOT),
    )


from edge.vision.camera import (
    GStreamerCameraRing,
)

from edge.vision.face_identity import (
    DEFAULT_MIN_IDENTITY_AREA_RATIO,
    OwnerFaceScorer,
    OwnerTemporalConsensus,
    resolve_owner_presence,
)


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--seconds",
        type=float,
        default=10.0,
    )

    parser.add_argument(
        "--label",
        default="test",
    )

    args = parser.parse_args()

    scorer = OwnerFaceScorer(
        detector_model=(
            REPO_ROOT
            / "models/face/"
            "face_detection_yunet_2023mar.onnx"
        ),
        recognizer_model=(
            REPO_ROOT
            / "models/face/"
            "face_recognition_sface_2021dec.onnx"
        ),
        exemplars_path=(
            REPO_ROOT
            / "private/faces/owner/"
            "embeddings/exemplars.npy"
        ),
        centroid_path=(
            REPO_ROOT
            / "private/faces/owner/"
            "embeddings/centroid.npy"
        ),
        detection_threshold=0.55,
    )

    consensus = (
        OwnerTemporalConsensus(
            window_size=5,
            required_votes=3,
        )
    )

    camera = GStreamerCameraRing(
        device="/dev/video0",
        width=1280,
        height=720,
        fps=10,
        directory=(
            "/dev/shm/"
            "luckrobot_owner_identity"
        ),
        max_files=20,
    )

    last_path = None
    frame_index = 0

    print(
        f"OWNER_IDENTITY_TEST "
        f"label={args.label}"
    )

    try:
        camera.start()

        camera.wait_for_frame(
            timeout_seconds=3.0
        )

        deadline = (
            time.monotonic()
            + args.seconds
        )

        while (
            time.monotonic()
            < deadline
        ):
            frame = (
                camera.ring
                .latest_frame()
            )

            if (
                frame is None
                or frame.path
                == last_path
            ):
                time.sleep(0.03)
                continue

            last_path = frame.path
            frame_index += 1

            observations = (
                scorer.analyze_jpeg(
                    frame.jpeg_bytes
                )
            )

            result = (
                resolve_owner_presence(
                    observations
                )
            )

            temporal = (
                consensus.update(
                    result
                )
            )

            usable = [
                item
                for item in observations
                if (
                    item.area_ratio
                    >=
                    DEFAULT_MIN_IDENTITY_AREA_RATIO
                )
            ]

            if result.owner is not None:
                selected = result.owner
                instant = "owner"

            elif usable:
                selected = max(
                    usable,
                    key=lambda item: (
                        min(
                            item.best_exemplar_cosine,
                            item.centroid_cosine,
                        )
                    ),
                )
                instant = "unknown"

            else:
                selected = None
                instant = "no_face"

            line = (
                f"FRAME={frame_index:03d} "
                f"detected="
                f"{len(observations)} "
                f"usable="
                f"{result.usable_face_count} "
                f"instant={instant} "
                f"stable={temporal.state} "
                f"votes="
                f"{temporal.owner_votes}/"
                f"{temporal.unknown_votes}"
            )

            if selected is not None:
                line += (
                    f" best="
                    f"{selected.best_exemplar_cosine:.4f}"
                    f" centroid="
                    f"{selected.centroid_cosine:.4f}"
                    f" area="
                    f"{selected.area_ratio:.4f}"
                )

            print(line)

            time.sleep(0.20)

    finally:
        camera.stop()

    final = consensus.update(
        resolve_owner_presence(())
    )

    print()
    print(
        "===== FINAL IDENTITY ====="
    )

    print(
        "LABEL=",
        args.label,
    )

    print(
        "STATE=",
        final.state,
    )

    print(
        "SAMPLES=",
        final.samples,
    )

    print(
        "OWNER_VOTES=",
        final.owner_votes,
    )

    print(
        "UNKNOWN_VOTES=",
        final.unknown_votes,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
