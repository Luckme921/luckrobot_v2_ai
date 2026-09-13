#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import numpy as np


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
    OwnerFaceScorer,
)


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--seconds",
        type=float,
        default=20.0,
    )

    parser.add_argument(
        "--label",
        default="calibration",
    )

    args = parser.parse_args()

    root = REPO_ROOT

    scorer = OwnerFaceScorer(
        detector_model=(
            root
            / "models/face/"
            "face_detection_yunet_2023mar.onnx"
        ),
        recognizer_model=(
            root
            / "models/face/"
            "face_recognition_sface_2021dec.onnx"
        ),
        exemplars_path=(
            root
            / "private/faces/owner/"
            "embeddings/exemplars.npy"
        ),
        centroid_path=(
            root
            / "private/faces/owner/"
            "embeddings/centroid.npy"
        ),
        detection_threshold=0.55,
    )

    camera = GStreamerCameraRing(
        device="/dev/video0",
        width=1280,
        height=720,
        fps=10,
        directory=(
            "/dev/shm/"
            "luckrobot_face_identity"
        ),
        max_files=20,
    )

    frame_index = 0
    last_path = None

    selected_best = []
    selected_center = []

    try:
        camera.start()

        camera.wait_for_frame(
            timeout_seconds=3.0
        )

        print(
            f"FACE_TEST label={args.label} "
            f"seconds={args.seconds:.1f}"
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

            if not observations:
                print(
                    f"FRAME={frame_index:03d} "
                    "faces=0"
                )
                time.sleep(0.25)
                continue

            # Observations are ordered by
            # owner-likeness. This means a
            # second false face no longer
            # discards the real face.
            selected = observations[0]

            selected_best.append(
                selected
                .best_exemplar_cosine
            )

            selected_center.append(
                selected
                .centroid_cosine
            )

            print(
                f"FRAME={frame_index:03d} "
                f"faces={len(observations)} "
                f"best="
                f"{selected.best_exemplar_cosine:.4f} "
                f"centroid="
                f"{selected.centroid_cosine:.4f} "
                f"det="
                f"{selected.detection_score:.3f} "
                f"area="
                f"{selected.area_ratio:.4f}"
            )

            if len(observations) > 1:
                for index, item in enumerate(
                    observations[1:],
                    start=1,
                ):
                    print(
                        f"  ALT={index} "
                        f"best="
                        f"{item.best_exemplar_cosine:.4f} "
                        f"centroid="
                        f"{item.centroid_cosine:.4f} "
                        f"det="
                        f"{item.detection_score:.3f} "
                        f"area="
                        f"{item.area_ratio:.4f}"
                    )

            time.sleep(0.25)

    finally:
        camera.stop()

    print()
    print(
        "===== SCORE SUMMARY ====="
    )

    print(
        "LABEL=",
        args.label,
    )

    print(
        "VALID_FRAMES=",
        len(selected_best),
    )

    if selected_best:
        best = np.asarray(
            selected_best
        )

        center = np.asarray(
            selected_center
        )

        print(
            "BEST_MIN="
            f"{best.min():.4f}"
        )
        print(
            "BEST_P10="
            f"{np.percentile(best, 10):.4f}"
        )
        print(
            "BEST_MEDIAN="
            f"{np.median(best):.4f}"
        )
        print(
            "BEST_MAX="
            f"{best.max():.4f}"
        )

        print(
            "CENTROID_MIN="
            f"{center.min():.4f}"
        )
        print(
            "CENTROID_P10="
            f"{np.percentile(center, 10):.4f}"
        )
        print(
            "CENTROID_MEDIAN="
            f"{np.median(center):.4f}"
        )
        print(
            "CENTROID_MAX="
            f"{center.max():.4f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
