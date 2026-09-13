from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

import numpy as np


class FaceIdentityError(RuntimeError):
    pass


@dataclass(frozen=True)
class FaceIdentityObservation:
    box: tuple[
        float,
        float,
        float,
        float,
    ]
    detection_score: float
    area_ratio: float
    best_exemplar_cosine: float
    centroid_cosine: float


def _normalize_vector(
    value: np.ndarray,
) -> np.ndarray:
    vector = np.asarray(
        value,
        dtype=np.float32,
    ).reshape(-1)

    norm = float(
        np.linalg.norm(
            vector
        )
    )

    if norm <= 1e-8:
        raise ValueError(
            "embedding norm is zero"
        )

    return (
        vector
        / norm
    ).astype(
        np.float32
    )


def score_owner_embedding(
    embedding: np.ndarray,
    exemplars: np.ndarray,
    centroid: np.ndarray,
) -> tuple[
    float,
    float,
]:
    feature = _normalize_vector(
        embedding
    )

    gallery = np.asarray(
        exemplars,
        dtype=np.float32,
    )

    if gallery.ndim != 2:
        raise ValueError(
            "exemplars must be 2-D"
        )

    if gallery.shape[0] <= 0:
        raise ValueError(
            "exemplars must not be empty"
        )

    if (
        gallery.shape[1]
        != feature.size
    ):
        raise ValueError(
            "embedding dimension mismatch"
        )

    gallery_norms = np.linalg.norm(
        gallery,
        axis=1,
        keepdims=True,
    )

    if np.any(
        gallery_norms
        <= 1e-8
    ):
        raise ValueError(
            "exemplar norm is zero"
        )

    gallery = (
        gallery
        / gallery_norms
    )

    center = _normalize_vector(
        centroid
    )

    if center.size != feature.size:
        raise ValueError(
            "centroid dimension mismatch"
        )

    best = float(
        np.max(
            gallery
            @ feature
        )
    )

    center_score = float(
        np.dot(
            center,
            feature,
        )
    )

    return (
        best,
        center_score,
    )


class OwnerFaceScorer:
    def __init__(
        self,
        *,
        detector_model: str | Path,
        recognizer_model: str | Path,
        exemplars_path: str | Path,
        centroid_path: str | Path,
        detection_threshold: float = 0.55,
    ) -> None:
        try:
            import cv2
        except ImportError as exc:
            raise FaceIdentityError(
                "OpenCV is not installed"
            ) from exc

        self._cv2 = cv2

        self.detector_model = Path(
            detector_model
        )
        self.recognizer_model = Path(
            recognizer_model
        )

        self.exemplars = np.load(
            exemplars_path
        ).astype(
            np.float32
        )

        self.centroid = np.load(
            centroid_path
        ).astype(
            np.float32
        )

        if self.exemplars.ndim != 2:
            raise FaceIdentityError(
                "Invalid owner exemplars"
            )

        if (
            self.centroid.reshape(-1).size
            != self.exemplars.shape[1]
        ):
            raise FaceIdentityError(
                "Owner template dimension "
                "mismatch"
            )

        self.detection_threshold = float(
            detection_threshold
        )

        self.detector = (
            cv2.FaceDetectorYN.create(
                str(
                    self.detector_model
                ),
                "",
                (
                    320,
                    320,
                ),
                self.detection_threshold,
                0.3,
                5000,
            )
        )

        self.recognizer = (
            cv2.FaceRecognizerSF.create(
                str(
                    self.recognizer_model
                ),
                "",
            )
        )

    def analyze_jpeg(
        self,
        jpeg_bytes: bytes,
    ) -> tuple[
        FaceIdentityObservation,
        ...,
    ]:
        data = np.frombuffer(
            jpeg_bytes,
            dtype=np.uint8,
        )

        image = self._cv2.imdecode(
            data,
            self._cv2.IMREAD_COLOR,
        )

        if image is None:
            raise FaceIdentityError(
                "Could not decode JPEG"
            )

        return self.analyze_bgr(
            image
        )

    def analyze_bgr(
        self,
        image: np.ndarray,
    ) -> tuple[
        FaceIdentityObservation,
        ...,
    ]:
        if (
            image is None
            or image.ndim != 3
        ):
            raise FaceIdentityError(
                "Invalid BGR image"
            )

        height, width = (
            image.shape[:2]
        )

        if (
            width <= 0
            or height <= 0
        ):
            raise FaceIdentityError(
                "Invalid image dimensions"
            )

        self.detector.setInputSize(
            (
                width,
                height,
            )
        )

        _, faces = (
            self.detector.detect(
                image
            )
        )

        if faces is None:
            return ()

        observations = []

        for face in faces:
            try:
                aligned = (
                    self.recognizer
                    .alignCrop(
                        image,
                        face,
                    )
                )

                embedding = np.asarray(
                    self.recognizer
                    .feature(
                        aligned
                    ),
                    dtype=np.float32,
                ).reshape(-1)

                best, center = (
                    score_owner_embedding(
                        embedding,
                        self.exemplars,
                        self.centroid,
                    )
                )

            except Exception:
                # One bad/false detection must
                # not invalidate other faces.
                continue

            x = float(face[0])
            y = float(face[1])
            box_width = float(
                face[2]
            )
            box_height = float(
                face[3]
            )

            observations.append(
                FaceIdentityObservation(
                    box=(
                        x,
                        y,
                        box_width,
                        box_height,
                    ),
                    detection_score=float(
                        face[-1]
                    ),
                    area_ratio=(
                        box_width
                        * box_height
                        / float(
                            width
                            * height
                        )
                    ),
                    best_exemplar_cosine=(
                        best
                    ),
                    centroid_cosine=(
                        center
                    ),
                )
            )

        observations.sort(
            key=lambda item: (
                min(
                    item
                    .best_exemplar_cosine,
                    item
                    .centroid_cosine,
                ),
                item.detection_score,
                item.area_ratio,
            ),
            reverse=True,
        )

        return tuple(
            observations
        )


DEFAULT_OWNER_BEST_THRESHOLD = 0.34
DEFAULT_OWNER_CENTROID_THRESHOLD = 0.34
DEFAULT_MIN_IDENTITY_AREA_RATIO = 0.01


@dataclass(frozen=True)
class OwnerPresenceResult:
    owner_present: bool
    usable_face_count: int
    unknown_face_count: int
    owner: FaceIdentityObservation | None


def resolve_owner_presence(
    observations: tuple[
        FaceIdentityObservation,
        ...
    ],
    *,
    best_threshold: float = (
        DEFAULT_OWNER_BEST_THRESHOLD
    ),
    centroid_threshold: float = (
        DEFAULT_OWNER_CENTROID_THRESHOLD
    ),
    min_area_ratio: float = (
        DEFAULT_MIN_IDENTITY_AREA_RATIO
    ),
) -> OwnerPresenceResult:
    usable = [
        item
        for item in observations
        if item.area_ratio
        >= min_area_ratio
    ]

    owner_candidates = [
        item
        for item in usable
        if (
            item.best_exemplar_cosine
            >= best_threshold
            and
            item.centroid_cosine
            >= centroid_threshold
        )
    ]

    owner = None

    if owner_candidates:
        owner = max(
            owner_candidates,
            key=lambda item: (
                min(
                    item.best_exemplar_cosine,
                    item.centroid_cosine,
                ),
                item.detection_score,
            ),
        )

    return OwnerPresenceResult(
        owner_present=(
            owner is not None
        ),
        usable_face_count=len(
            usable
        ),
        unknown_face_count=(
            len(usable)
            - (
                1
                if owner is not None
                else 0
            )
        ),
        owner=owner,
    )



@dataclass(frozen=True)
class OwnerTemporalResult:
    state: str
    samples: int
    owner_votes: int
    unknown_votes: int


class OwnerTemporalConsensus:
    def __init__(
        self,
        *,
        window_size: int = 5,
        required_votes: int = 3,
        stale_after_seconds: float = 2.0,
    ) -> None:
        self.window_size = int(
            window_size
        )
        self.required_votes = int(
            required_votes
        )
        self.stale_after_seconds = float(
            stale_after_seconds
        )

        if self.window_size <= 0:
            raise ValueError(
                "window_size must be > 0"
            )

        if (
            self.required_votes <= 0
            or self.required_votes
            > self.window_size
        ):
            raise ValueError(
                "invalid required_votes"
            )

        if self.stale_after_seconds <= 0:
            raise ValueError(
                "stale_after_seconds must be > 0"
            )

        self._votes: list[bool] = []
        self._last_evidence_at: (
            float | None
        ) = None

    def reset(
        self,
    ) -> None:
        self._votes.clear()
        self._last_evidence_at = None

    def update(
        self,
        result: OwnerPresenceResult,
        *,
        now: float | None = None,
    ) -> OwnerTemporalResult:
        if now is None:
            now = time.monotonic()

        # A short detector dropout must not
        # immediately erase identity state.
        # But old identity evidence must expire.
        if result.usable_face_count > 0:
            self._votes.append(
                result.owner_present
            )

            self._last_evidence_at = now

            if (
                len(self._votes)
                > self.window_size
            ):
                self._votes = (
                    self._votes[
                        -self.window_size:
                    ]
                )

        elif (
            self._last_evidence_at
            is not None
            and
            (
                now
                - self._last_evidence_at
            )
            >= self.stale_after_seconds
        ):
            self.reset()

        owner_votes = sum(
            1
            for vote in self._votes
            if vote
        )

        unknown_votes = (
            len(self._votes)
            - owner_votes
        )

        if (
            owner_votes
            >= self.required_votes
        ):
            state = "owner"

        elif (
            unknown_votes
            >= self.required_votes
        ):
            state = "unknown"

        else:
            state = "uncertain"

        return OwnerTemporalResult(
            state=state,
            samples=len(
                self._votes
            ),
            owner_votes=owner_votes,
            unknown_votes=unknown_votes,
        )
