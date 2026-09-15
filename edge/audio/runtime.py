from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import time

import numpy as np
import yaml

from edge.agent.cloud_client import (
    CloudAgentClient,
    CloudAgentError,
)
from edge.audio.asr.sensevoice import (
    SenseVoiceRecognizer,
)
from edge.audio.capture.pulse import (
    PulseCapture,
    PulseCaptureError,
)
from edge.audio.device_resolver.pulse import (
    PulseDeviceNotFound,
    resolve_microphone,
    resolve_speaker,
)
from edge.audio.tts.kokoro import (
    KokoroTts,
    TtsError,
)
from edge.audio.vad.silero import (
    SileroVad,
)
from edge.audio.wake.kws import (
    WakeKeywordSpotter,
)
from edge.audio.wake.session import (
    InteractionGate,
)
from edge.vision.camera import (
    CameraError,
    GStreamerCameraRing,
)
from edge.vision.runtime_bridge import (
    VisionSelectionError,
    capture_turn_snapshot,
    select_turn_snapshot_frames,
)
from edge.vision.face_identity import (
    OwnerFaceScorer,
)
from edge.vision.identity_runtime import (
    classify_turn_identity,
)


def load_config(
    path: str,
) -> dict:
    with open(
        path,
        "r",
        encoding="utf-8",
    ) as f:
        return yaml.safe_load(f)


def create_vad(
    config: dict,
    sample_rate: int,
) -> SileroVad:
    return SileroVad(
        model=config["model"],
        sample_rate=sample_rate,
        threshold=float(
            config["threshold"]
        ),
        min_silence_duration=float(
            config[
                "min_silence_duration"
            ]
        ),
        min_speech_duration=float(
            config[
                "min_speech_duration"
            ]
        ),
        max_speech_duration=float(
            config[
                "max_speech_duration"
            ]
        ),
        buffer_size_seconds=int(
            config[
                "buffer_size_seconds"
            ]
        ),
        num_threads=int(
            config["num_threads"]
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--config",
        default="configs/audio.yaml",
    )

    parser.add_argument(
        "--vision-config",
        default="configs/vision.yaml",
    )

    args = parser.parse_args()

    config = load_config(
        args.config
    )

    vision_config = load_config(
        args.vision_config
    )

    vision_cfg = vision_config.get(
        "vision",
        {},
    )

    audio_cfg = config["audio"]
    vad_cfg = config["vad"]
    asr_cfg = config["asr"]
    interaction_cfg = config[
        "interaction"
    ]

    wake_cfg = interaction_cfg[
        "wake"
    ]

    followup_cfg = interaction_cfg[
        "followup"
    ]

    agent_bridge_cfg = config.get(
        "agent_bridge",
        {},
    )

    agent_bridge_enabled = bool(
        agent_bridge_cfg.get(
            "enabled",
            False,
        )
    )

    agent_client = None

    if agent_bridge_enabled:
        agent_client = CloudAgentClient(
            endpoint=str(
                agent_bridge_cfg[
                    "endpoint"
                ]
            ),
            timeout_seconds=float(
                agent_bridge_cfg.get(
                    "timeout_seconds",
                    35.0,
                )
            ),
            history_max_turns=int(
                agent_bridge_cfg.get(
                    "history_max_turns",
                    100,
                )
            ),
            memory_db_path=(
                Path(__file__)
                .resolve()
                .parents[2]
                / str(
                    agent_bridge_cfg.get(
                        "memory_db_path",
                        (
                            "private/memory/"
                            "conversation.sqlite3"
                        ),
                    )
                )
            ),
            compact_batch_turns=int(
                agent_bridge_cfg.get(
                    "compact_batch_turns",
                    100,
                )
            ),
            archive_retrieval_limit=int(
                agent_bridge_cfg.get(
                    "archive_retrieval_limit",
                    6,
                )
            ),
        )

    vision_camera = None

    if bool(
        vision_cfg.get(
            "enabled",
            False,
        )
    ):
        camera_cfg = vision_cfg[
            "camera"
        ]

        ring_cfg = vision_cfg[
            "ring_buffer"
        ]

        vision_camera = (
            GStreamerCameraRing(
                device=str(
                    camera_cfg[
                        "device"
                    ]
                ),
                width=int(
                    camera_cfg[
                        "width"
                    ]
                ),
                height=int(
                    camera_cfg[
                        "height"
                    ]
                ),
                fps=int(
                    camera_cfg[
                        "fps"
                    ]
                ),
                directory=str(
                    ring_cfg[
                        "directory"
                    ]
                ),
                max_files=int(
                    ring_cfg[
                        "max_files"
                    ]
                ),
            )
        )

    identity_cfg = vision_cfg.get(
        "face_identity",
        {},
    )

    identity_scorer = None

    if bool(
        identity_cfg.get(
            "enabled",
            False,
        )
    ):
        if vision_camera is None:
            print(
                "[IDENTITY] DISABLED "
                "reason=vision_camera_disabled",
                flush=True,
            )

        else:
            repo_root = (
                Path(__file__)
                .resolve()
                .parents[2]
            )

            try:
                identity_scorer = (
                    OwnerFaceScorer(
                        detector_model=(
                            repo_root
                            / str(
                                identity_cfg[
                                    "detector_model"
                                ]
                            )
                        ),
                        recognizer_model=(
                            repo_root
                            / str(
                                identity_cfg[
                                    "recognizer_model"
                                ]
                            )
                        ),
                        exemplars_path=(
                            repo_root
                            / str(
                                identity_cfg[
                                    "exemplars_path"
                                ]
                            )
                        ),
                        centroid_path=(
                            repo_root
                            / str(
                                identity_cfg[
                                    "centroid_path"
                                ]
                            )
                        ),
                        detection_threshold=float(
                            identity_cfg.get(
                                "detection_threshold",
                                0.55,
                            )
                        ),
                    )
                )

                print(
                    "[INIT] Owner face "
                    "identity ready.",
                    flush=True,
                )

            except Exception as exc:
                print(
                    "[IDENTITY] INIT_ERROR "
                    f"{type(exc).__name__}: "
                    f"{exc}",
                    flush=True,
                )

                identity_scorer = None

    tts_cfg = config.get(
        "tts",
        {},
    )

    tts_enabled = bool(
        tts_cfg.get(
            "enabled",
            False,
        )
    )

    post_playback_guard_seconds = float(
        tts_cfg.get(
            "post_playback_guard_seconds",
            0.6,
        )
    )

    tts = None

    if tts_enabled:
        provider = str(
            tts_cfg.get(
                "provider",
                "kokoro",
            )
        ).strip().lower()

        if provider != "kokoro":
            print(
                "[TTS] ERROR "
                f"unsupported provider="
                f"{provider}",
                flush=True,
            )
        else:
            print(
                "[INIT] Loading "
                "Kokoro TTS...",
                flush=True,
            )

            t0 = time.monotonic()

            try:
                tts = KokoroTts(
                    tts_cfg
                )

                print(
                    "[INIT] Kokoro TTS "
                    "ready "
                    f"speaker_id="
                    f"{tts.speaker_id} "
                    f"threads="
                    f"{tts.num_threads} "
                    f"load="
                    f"{time.monotonic() - t0:.3f}s",
                    flush=True,
                )

            except TtsError as exc:
                print(
                    "[TTS] INIT_ERROR "
                    f"{exc}",
                    flush=True,
                )

                tts = None

    sample_rate = int(
        audio_cfg["sample_rate"]
    )

    asr_context_pre_seconds = float(
        asr_cfg.get(
            "context_pre_seconds",
            0.30,
        )
    )

    asr_context_post_seconds = float(
        asr_cfg.get(
            "context_post_seconds",
            0.20,
        )
    )

    retry_seconds = float(
        audio_cfg.get(
            "reconnect_interval_seconds",
            1.0,
        )
    )

    wake_enabled = bool(
        wake_cfg.get(
            "enabled",
            True,
        )
    )

    interaction_gate = (
        InteractionGate(
            wake_command_timeout_seconds=float(
                wake_cfg[
                    "wake_command_timeout_seconds"
                ]
            ),
            normal_timeout_seconds=float(
                followup_cfg[
                    "normal_timeout_seconds"
                ]
            ),
            chat_timeout_seconds=float(
                followup_cfg[
                    "chat_timeout_seconds"
                ]
            ),
            transcript_aliases=(
                wake_cfg.get(
                    "transcript_aliases",
                    ["lucky"],
                )
            ),
            transcript_exact_aliases=(
                wake_cfg.get(
                    "transcript_exact_aliases",
                    [],
                )
            ),
            chat_mode_triggers=(
                interaction_cfg[
                    "chat_mode_triggers"
                ]
            ),
            sleep_phrases=(
                interaction_cfg[
                    "sleep_phrases"
                ]
            ),
            emergency_stop_phrases=(
                interaction_cfg[
                    "emergency_stop_phrases"
                ]
            ),
            enabled=wake_enabled,
        )
    )

    debug_log_transcript = bool(
        interaction_cfg.get(
            "debug_log_transcript",
            False,
        )
    )

    wake_kws = None

    if wake_enabled:
        print(
            "[INIT] Loading Lucky KWS..."
        )

        wake_kws = (
            WakeKeywordSpotter(
                wake_cfg,
                sample_rate,
            )
        )

        print(
            "[INIT] Lucky KWS ready."
        )

    print(
        "[INIT] Loading SenseVoice..."
    )

    # Keep ASR resident so the first command
    # after wake-up does not pay model startup
    # latency.
    asr = SenseVoiceRecognizer(
        model_dir=asr_cfg[
            "model_dir"
        ],
        provider=asr_cfg[
            "provider"
        ],
        num_threads=int(
            asr_cfg[
                "num_threads"
            ]
        ),
        language=asr_cfg[
            "language"
        ],
        use_itn=bool(
            asr_cfg[
                "use_itn"
            ]
        ),
    )

    print(
        "[INIT] SenseVoice ready."
    )

    if vision_camera is not None:
        print(
            "[INIT] Starting "
            "interaction camera...",
            flush=True,
        )

        try:
            vision_camera.start()

            first_frame = (
                vision_camera
                .wait_for_frame(
                    4.0
                )
            )

            print(
                "[VISION] CAMERA_OK "
                f"bytes="
                f"{len(first_frame.jpeg_bytes)} "
                f"buffer="
                f"{vision_camera.directory}",
                flush=True,
            )

        except CameraError as exc:
            print(
                "[VISION] CAMERA_ERROR "
                f"{exc}",
                flush=True,
            )

            vision_camera.stop()
            vision_camera = None

    state = None

    try:
        while True:
            try:
                print(
                    "[AUDIO] Resolving USB devices..."
                )

                microphone = (
                    resolve_microphone(
                        audio_cfg[
                            "microphone"
                        ][
                            "match_any"
                        ]
                    )
                )

                try:
                    speaker = (
                        resolve_speaker(
                            audio_cfg[
                                "speaker"
                            ][
                                "match_any"
                            ]
                        )
                    )
                except PulseDeviceNotFound:
                    speaker = (
                        "<unavailable>"
                    )

                print(
                    "[AUDIO] "
                    f"microphone={microphone}"
                )

                print(
                    "[AUDIO] "
                    f"speaker={speaker}"
                )

                vad = create_vad(
                    vad_cfg,
                    sample_rate,
                )

                interaction_gate.reset()

                wake_stream = (
                    wake_kws.create_stream()
                    if wake_kws
                    else None
                )

                microphone_cfg = (
                    audio_cfg[
                        "microphone"
                    ]
                )

                selected_channel = (
                    microphone_cfg.get(
                        "selected_channel"
                    )
                )

                capture = PulseCapture(
                    source=microphone,
                    sample_rate=sample_rate,
                    channels=int(
                        audio_cfg[
                            "channels"
                        ]
                    ),
                    sample_format=(
                        audio_cfg[
                            "format"
                        ]
                    ),
                    input_channels=int(
                        microphone_cfg.get(
                            "input_channels",
                            audio_cfg[
                                "channels"
                            ],
                        )
                    ),
                    selected_channel=(
                        None
                        if selected_channel
                        is None
                        else int(
                            selected_channel
                        )
                    ),
                )

                print(
                    "[STATE] AUDIO_CONNECTING"
                )

                with capture:
                    state = "AUDIO_OK"

                    print(
                        "[STATE] AUDIO_OK"
                    )

                    print(
                        "[READY] Listening..."
                    )

                    print(
                        "[READY] "
                        "Press Ctrl+C to stop."
                    )

                    if wake_enabled:
                        print(
                            '[STATE] SLEEPING'
                        )
                        print(
                            '[WAKE] Waiting for "Lucky".'
                        )

                    zero_audio_samples = 0

                    zero_audio_limit = int(
                        sample_rate
                        * float(
                            audio_cfg.get(
                                "zero_audio_timeout_seconds",
                                1.0,
                            )
                        )
                    )

                    for pcm in capture.chunks(
                        vad.window_size
                    ):
                        samples = (
                            np.frombuffer(
                                pcm,
                                dtype=np.int16,
                            )
                            .astype(
                                np.float32
                            )
                            / 32768.0
                        )

                        if np.any(
                            samples
                        ):
                            if (
                                zero_audio_samples
                                >= zero_audio_limit
                                and state
                                == "AUDIO_DEGRADED"
                            ):
                                state = (
                                    "AUDIO_OK"
                                )

                                print(
                                    "[STATE] AUDIO_OK"
                                )

                                print(
                                    "[AUDIO] "
                                    "PCM stream recovered",
                                    flush=True,
                                )

                            zero_audio_samples = 0

                        else:
                            zero_audio_samples += (
                                len(samples)
                            )

                            if (
                                zero_audio_samples
                                >= zero_audio_limit
                                and state
                                != "AUDIO_DEGRADED"
                            ):
                                state = (
                                    "AUDIO_DEGRADED"
                                )

                                print(
                                    "[STATE] "
                                    "AUDIO_DEGRADED"
                                )

                                print(
                                    "[AUDIO] "
                                    "PCM stream is "
                                    "all-zero",
                                    flush=True,
                                )

                        now = (
                            time.monotonic()
                        )

                        if (
                            interaction_gate
                            .expire_if_needed(
                                now
                            )
                        ):
                            print(
                                "[STATE] SLEEPING "
                                "reason=timeout",
                                flush=True,
                            )

                            if agent_client is not None:
                                print(
                                    "[AGENT_MEMORY] PRESERVED "
                                    "reason=interaction_timeout "
                                    f"messages="
                                    f"{agent_client.history_messages}",
                                    flush=True,
                                )

                            if wake_kws:
                                wake_stream = (
                                    wake_kws
                                    .create_stream()
                                )

                        if (
                            wake_kws
                            and wake_stream
                            and interaction_gate.state
                            == InteractionGate.SLEEPING
                        ):
                            keyword = (
                                wake_kws.accept(
                                    wake_stream,
                                    samples,
                                )
                            )

                            if keyword:
                                if (
                                    agent_client
                                    is not None
                                ):
                                    print(
                                        "[AGENT_MEMORY] RESUME "
                                        f"messages="
                                        f"{agent_client.history_messages}",
                                        flush=True,
                                    )

                                interaction_gate.on_wake(
                                    now
                                )

                                print(
                                    "[WAKE] "
                                    "KWS_DETECTED "
                                    f"keyword={keyword}",
                                    flush=True,
                                )

                                print(
                                    "[STATE] "
                                    "AWAKE_WAIT_COMMAND",
                                    flush=True,
                                )

                        # VAD is kept lightweight and
                        # continuously fed so the segment
                        # containing Lucky + command can
                        # still be recovered.
                        vad.accept(
                            samples
                        )

                        while vad.has_segment():
                            (
                                segment,
                                asr_samples,
                            ) = (
                                vad.pop_segment_with_context(
                                    pre_seconds=(
                                        asr_context_pre_seconds
                                    ),
                                    post_seconds=(
                                        asr_context_post_seconds
                                    ),
                                )
                            )

                            # While sleeping, ambient
                            # speech is discarded without
                            # invoking SenseVoice.
                            if (
                                wake_enabled
                                and
                                interaction_gate.state
                                == InteractionGate.SLEEPING
                            ):
                                continue

                            start_sec = (
                                segment.start
                                / sample_rate
                            )

                            duration_sec = (
                                len(
                                    segment.samples
                                )
                                / sample_rate
                            )

                            t0 = (
                                time.monotonic()
                            )

                            text = (
                                asr.transcribe(
                                    asr_samples,
                                    sample_rate,
                                )
                            )

                            elapsed = (
                                time.monotonic()
                                - t0
                            )

                            if not text:
                                continue

                            print(
                                "[ASR] "
                                f"start={start_sec:.2f}s "
                                f"duration={duration_sec:.2f}s "
                                f"inference={elapsed:.3f}s"
                            )

                            if (
                                debug_log_transcript
                            ):
                                print(
                                    "[ASR_TEXT] "
                                    f"{text}",
                                    flush=True,
                                )

                            decision = (
                                interaction_gate
                                .process(
                                    text,
                                    now=time.monotonic(),
                                )
                            )

                            if (
                                decision.action
                                == "emergency_stop"
                            ):
                                print(
                                    "[EMERGENCY] "
                                    "LOCAL_STOP_REQUESTED",
                                    flush=True,
                                )

                            elif (
                                decision.action
                                == "awake"
                            ):
                                print(
                                    "[STATE] "
                                    "AWAKE_WAIT_COMMAND",
                                    flush=True,
                                )

                            elif (
                                decision.action
                                == "sleep"
                            ):
                                print(
                                    "[STATE] SLEEPING "
                                    "reason=user_request",
                                    flush=True,
                                )

                                if (
                                    agent_client
                                    is not None
                                ):
                                    print(
                                        "[AGENT_MEMORY] PRESERVED "
                                        "reason=user_sleep "
                                        f"messages="
                                        f"{agent_client.history_messages}",
                                        flush=True,
                                    )

                                if wake_kws:
                                    wake_stream = (
                                        wake_kws
                                        .create_stream()
                                    )

                            elif (
                                decision.action
                                == "command"
                            ):
                                print(
                                    "[COMMAND] "
                                    f"{decision.command}",
                                    flush=True,
                                )

                                print(
                                    "[SESSION] "
                                    f"mode={decision.mode}",
                                    flush=True,
                                )

                                if (
                                    agent_client
                                    is not None
                                ):
                                    print(
                                        "[STATE] THINKING",
                                        flush=True,
                                    )

                                    turn_vision_snapshot = None

                                    if (
                                        vision_camera
                                        is not None
                                        and
                                        vision_camera.running
                                    ):
                                        turn_vision_snapshot = (
                                            capture_turn_snapshot(
                                                vision_camera.ring,
                                                recent_seconds=6.0,
                                                recent_count=16,
                                            )
                                        )

                                        print(
                                            "[VISION] TURN_SNAPSHOT "
                                            f"latest="
                                            f"{1 if turn_vision_snapshot.latest is not None else 0} "
                                            f"recent="
                                            f"{len(turn_vision_snapshot.recent)}",
                                            flush=True,
                                        )

                                    # V1 is half duplex.
                                    # Stop microphone capture
                                    # while local perception and
                                    # the Cloud Agent process
                                    # this command.
                                    capture.stop()

                                    # One semantic identity state is
                                    # frozen for this complete turn.
                                    # The same value is reused if the
                                    # Agent later requests vision.
                                    turn_identity_state = (
                                        "uncertain"
                                    )

                                    if (
                                        identity_scorer
                                        is not None
                                        and
                                        turn_vision_snapshot
                                        is not None
                                    ):
                                        identity_t0 = (
                                            time.monotonic()
                                        )

                                        try:
                                            identity_result = (
                                                classify_turn_identity(
                                                    turn_vision_snapshot,
                                                    identity_scorer,
                                                    sample_count=int(
                                                        identity_cfg.get(
                                                            "sample_count",
                                                            5,
                                                        )
                                                    ),
                                                    required_votes=int(
                                                        identity_cfg.get(
                                                            "required_votes",
                                                            3,
                                                        )
                                                    ),
                                                    best_threshold=float(
                                                        identity_cfg.get(
                                                            "best_threshold",
                                                            0.34,
                                                        )
                                                    ),
                                                    centroid_threshold=float(
                                                        identity_cfg.get(
                                                            "centroid_threshold",
                                                            0.34,
                                                        )
                                                    ),
                                                    min_area_ratio=float(
                                                        identity_cfg.get(
                                                            "min_area_ratio",
                                                            0.01,
                                                        )
                                                    ),
                                                )
                                            )

                                            turn_identity_state = (
                                                identity_result.state
                                            )

                                            print(
                                                "[IDENTITY] "
                                                f"state="
                                                f"{identity_result.state} "
                                                f"sampled="
                                                f"{identity_result.sampled_frames} "
                                                f"usable="
                                                f"{identity_result.usable_votes} "
                                                f"owner_votes="
                                                f"{identity_result.owner_votes} "
                                                f"unknown_votes="
                                                f"{identity_result.unknown_votes} "
                                                f"latency="
                                                f"{time.monotonic() - identity_t0:.3f}s",
                                                flush=True,
                                            )

                                        except Exception as exc:
                                            print(
                                                "[IDENTITY] ERROR "
                                                f"{type(exc).__name__}: "
                                                f"{exc}",
                                                flush=True,
                                            )

                                    playback_happened = False

                                    try:
                                        agent_t0 = time.monotonic()

                                        command_text = (
                                            decision.command
                                            or ""
                                        )

                                        agent_reply = (
                                            agent_client
                                            .chat(
                                                command_text,
                                                local_identity=(
                                                    turn_identity_state
                                                ),
                                            )
                                        )

                                        if (
                                            agent_reply
                                            .vision_request
                                            is not None
                                        ):
                                            if (
                                                turn_vision_snapshot
                                                is None
                                            ):
                                                raise (
                                                    CloudAgentError(
                                                        "Vision was "
                                                        "requested but "
                                                        "no turn-aligned "
                                                        "snapshot is "
                                                        "available"
                                                    )
                                                )

                                            vision_request = (
                                                agent_reply
                                                .vision_request
                                            )

                                            print(
                                                "[VISION] FULFILL "
                                                f"mode="
                                                f"{vision_request.mode} "
                                                f"seconds="
                                                f"{vision_request.seconds:.1f} "
                                                f"count="
                                                f"{vision_request.count}",
                                                flush=True,
                                            )

                                            vision_t0 = (
                                                time.monotonic()
                                            )

                                            frames = (
                                                select_turn_snapshot_frames(
                                                    turn_vision_snapshot,
                                                    vision_request,
                                                )
                                            )

                                            print(
                                                "[VISION] "
                                                "SELECTED_FRAMES "
                                                f"count="
                                                f"{len(frames)}",
                                                flush=True,
                                            )

                                            agent_reply = (
                                                agent_client
                                                .chat(
                                                    command_text,
                                                    jpeg_frames=[
                                                        frame
                                                        .jpeg_bytes
                                                        for frame
                                                        in frames
                                                    ],
                                                    local_identity=(
                                                        turn_identity_state
                                                    ),
                                                )
                                            )

                                            if (
                                                agent_reply
                                                .vision_request
                                                is not None
                                            ):
                                                raise (
                                                    CloudAgentError(
                                                        "Unexpected "
                                                        "repeated vision "
                                                        "request"
                                                    )
                                                )

                                            print(
                                                "[LATENCY] "
                                                "vision_followup="
                                                f"{time.monotonic() - vision_t0:.3f}s",
                                                flush=True,
                                            )

                                        agent_seconds = (
                                            time.monotonic()
                                            - agent_t0
                                        )

                                        print(
                                            "[LATENCY] "
                                            f"agent="
                                            f"{agent_seconds:.3f}s",
                                            flush=True,
                                        )

                                        print(
                                            "[AGENT_REPLY] "
                                            f"{agent_reply.text}",
                                            flush=True,
                                        )

                                        print(
                                            "[AGENT] "
                                            f"model="
                                            f"{agent_reply.model}",
                                            flush=True,
                                        )

                                        if (
                                            tts is not None
                                            and speaker
                                            != "<unavailable>"
                                        ):
                                            print(
                                                "[STATE] SPEAKING",
                                                flush=True,
                                            )

                                            try:
                                                tts_result = (
                                                    tts.speak(
                                                        agent_reply.text,
                                                        speaker,
                                                    )
                                                )

                                                playback_happened = True

                                                rtf = (
                                                    tts_result
                                                    .generation_seconds
                                                    / tts_result
                                                    .audio_seconds
                                                )

                                                print(
                                                    "[TTS] OK "
                                                    f"speaker_id="
                                                    f"{tts.speaker_id} "
                                                    f"generation="
                                                    f"{tts_result.generation_seconds:.3f}s "
                                                    f"audio="
                                                    f"{tts_result.audio_seconds:.3f}s "
                                                    f"rtf={rtf:.3f} "
                                                    f"sample_rate="
                                                    f"{tts_result.sample_rate}",
                                                    flush=True,
                                                )

                                                print(
                                                    "[LATENCY] "
                                                    f"tts_first_audio="
                                                    f"{tts_result.first_audio_latency_seconds:.3f}s "
                                                    f"tts_wall="
                                                    f"{tts_result.wall_seconds:.3f}s "
                                                    f"chunks="
                                                    f"{tts_result.chunks} "
                                                    f"agent_to_voice="
                                                    f"{agent_seconds + tts_result.first_audio_latency_seconds:.3f}s",
                                                    flush=True,
                                                )

                                            except TtsError as exc:
                                                print(
                                                    "[TTS] ERROR "
                                                    f"{exc}",
                                                    flush=True,
                                                )

                                        elif (
                                            tts is not None
                                        ):
                                            print(
                                                "[TTS] ERROR "
                                                "speaker unavailable",
                                                flush=True,
                                            )

                                    except (
                                        CloudAgentError,
                                        VisionSelectionError,
                                    ) as exc:
                                        print(
                                            "[AGENT] ERROR "
                                            f"{exc}",
                                            flush=True,
                                        )

                                    finally:
                                        # Start a clean VAD
                                        # context after THINKING,
                                        # so buffered/stale audio
                                        # cannot become a follow-up.
                                        vad = create_vad(
                                            vad_cfg,
                                            sample_rate,
                                        )

                                        zero_audio_samples = 0

                                        (
                                            interaction_gate
                                            .on_robot_reply_finished(
                                                time.monotonic()
                                            )
                                        )

                                        if (
                                            playback_happened
                                            and
                                            post_playback_guard_seconds
                                            > 0
                                        ):
                                            print(
                                                "[AUDIO] "
                                                "POST_TTS_GUARD "
                                                f"{post_playback_guard_seconds:.2f}s",
                                                flush=True,
                                            )

                                            time.sleep(
                                                post_playback_guard_seconds
                                            )

                                        print(
                                            "[STATE] LISTENING",
                                            flush=True,
                                        )

                                        capture.start()

            except (
                PulseDeviceNotFound,
                PulseCaptureError,
                subprocess.CalledProcessError,
            ) as exc:
                if (
                    state
                    != "AUDIO_DEGRADED"
                ):
                    print(
                        "[STATE] "
                        "AUDIO_DEGRADED"
                    )

                state = (
                    "AUDIO_DEGRADED"
                )

                print(
                    "[AUDIO] "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                print(
                    "[AUDIO] "
                    f"Retrying in "
                    f"{retry_seconds:.1f}s..."
                )

                time.sleep(
                    retry_seconds
                )

    except KeyboardInterrupt:
        print(
            "\n[STOP] "
            "Audio runtime stopped."
        )

    finally:
        if vision_camera is not None:
            vision_camera.stop()

            print(
                "[VISION] CAMERA_STOPPED",
                flush=True,
            )


if __name__ == "__main__":
    main()
