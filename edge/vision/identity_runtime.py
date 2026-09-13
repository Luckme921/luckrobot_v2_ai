from __future__ import annotations

from dataclasses import dataclass

from edge.vision.face_identity import (
    DEFAULT_MIN_IDENTITY_AREA_RATIO,
    DEFAULT_OWNER_BEST_THRESHOLD,
    DEFAULT_OWNER_CENTROID_THRESHOLD,
    resolve_owner_presence,
)
from edge.vision.runtime_bridge import (
    TurnVisionSnapshot,
)


@dataclass(frozen=True)
class TurnIdentityResult:
    state: str
    sampled_frames: int
    usable_votes: int
    owner_votes: int
    unknown_votes: int


def classify_turn_identity(
    snapshot: TurnVisionSnapshot,
    scorer,
    *,
    sample_count: int = 5,
    required_votes: int = 3,
    best_threshold: float = (
        DEFAULT_OWNER_BEST_THRESHOLD
    ),
    centroid_threshold: float = (
        DEFAULT_OWNER_CENTROID_THRESHOLD
    ),
    min_area_ratio: float = (
        DEFAULT_MIN_IDENTITY_AREA_RATIO
    ),
) -> TurnIdentityResult:
    sample_count = int(
        sample_count
    )

    required_votes = int(
        required_votes
    )

    if sample_count <= 0:
        raise ValueError(
            "sample_count must be > 0"
        )

    if (
        required_votes <= 0
        or required_votes > sample_count
    ):
        raise ValueError(
            "invalid required_votes"
        )

    # The turn snapshot is already frozen
    # relative to the accepted user command.
    # Use only its newest frames.
    frames = list(
        snapshot.recent[
            -sample_count:
        ]
    )

    owner_votes = 0
    unknown_votes = 0

    for frame in frames:
        observations = (
            scorer.analyze_jpeg(
                frame.jpeg_bytes
            )
        )

        result = (
            resolve_owner_presence(
                observations,
                best_threshold=(
                    best_threshold
                ),
                centroid_threshold=(
                    centroid_threshold
                ),
                min_area_ratio=(
                    min_area_ratio
                ),
            )
        )

        if (
            result.usable_face_count
            <= 0
        ):
            continue

        if result.owner_present:
            owner_votes += 1
        else:
            unknown_votes += 1

    usable_votes = (
        owner_votes
        + unknown_votes
    )

    if (
        owner_votes
        >= required_votes
        and
        owner_votes
        > unknown_votes
    ):
        state = "owner"

    elif (
        unknown_votes
        >= required_votes
        and
        unknown_votes
        > owner_votes
    ):
        state = "unknown"

    else:
        state = "uncertain"

    return TurnIdentityResult(
        state=state,
        sampled_frames=len(
            frames
        ),
        usable_votes=usable_votes,
        owner_votes=owner_votes,
        unknown_votes=unknown_votes,
    )
