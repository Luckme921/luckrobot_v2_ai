from __future__ import annotations

from edge.audio.volume import (
    PulseVolumeController,
    PulseVolumeError,
    parse_volume_command,
    volume_reply,
)

from edge.music.personal_library import (
    QQMusicPersonalLibrary,
)

from robot_tools.edge import build_edge_tools
from robot_tools.fan_light import FanLightController
from robot_tools.music import DirectAudioPlayer, MusicTools, has_explicit_music_intent

import builtins
from edge.audio.status import (
    configure_display,
    display_dialogue,
    display_music,
    display_light,
    display_voice_playing,
    display_state,
    status,
)
from edge.display.state import MUSIC_COVER_IMAGE
from edge.display.rolling_text import SpokenTextScroller
from edge.audio.conversation_log import ConversationLog
from robot_tools.batch import execute_plan, needs_semantic_route, result_message, REMOTE_SCHEMAS
from shared.errors import ERROR_MESSAGES
from edge.audio.barge_in import speak_with_wake, WakeInterruptMonitor
from edge.audio.tts.cancellation import SpeechInterrupted
from edge.audio.tts.streaming_reply import StreamingReplySpeaker

def print(*args, **kwargs):
    """Preserve diagnostic output and mirror meaningful states to status.log."""
    message = " ".join(str(arg) for arg in args)
    if 'Waiting for "Lucky"' in message or message.startswith("[STATE] SLEEPING"):
        status("等待 Lucky")
        display_state("sleeping", "等待 Lucky")
    elif message.startswith("[STATE] AWAKE_WAIT_COMMAND"):
        status("已唤醒，等待讲话")
        display_state("listening", "我在听")
    elif message.startswith("[STATE] LISTENING"):
        status("等待下一句话")
        display_state("listening", "等待下一句话")
    elif message.startswith("[STATE] SPEAKING"):
        status("文字转声音 / speak")
        display_state("speaking", "正在回答")
    elif message.startswith("[AGENT_REPLY]"):
        status("已得到回复")
    elif message.startswith("[WAKE] LOCAL_REPLY"):
        status("播放本地唤醒回应")
        display_state("speaking", "我在呢")
    if "reason=music_playback" in message:
        status("音乐播放中，等待 Lucky")
        display_state("music", "等待 Lucky")
    return builtins.print(*args, **kwargs)

import argparse
import json
from edge.audio.acknowledgement import ToolAcknowledgement, PHRASES
from edge.audio.tts.phrase_cache import ALL_PHRASES, WAKE_PHRASES, GOODBYE_PHRASES, cache_path, valid_clip, play_cached_reply
from shared.timing import begin_turn, measure, record, turn_started
from pathlib import Path
import subprocess
import threading
import time

import numpy as np
import yaml
from dotenv import load_dotenv

from edge.agent.cloud_client import (
    CloudAgentClient,
    AgentReply,
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
from edge.music.qqmusic import (
    QQMusicController,
    QQMusicError,
)
from edge.music import auth_bridge, control_bridge
from edge.vision.camera import (
    CameraError,
    GStreamerCameraRing,
)
from edge.vision.runtime_bridge import (
    VisionSelectionError,
    capture_turn_snapshot,
    explicit_vision_fast_path_tool_mode,
    infer_explicit_vision_fast_path,
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
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
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

    configure_display(config.get("display", {}))

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
            progress_enabled=bool(agent_bridge_cfg.get("progress_enabled", True)),
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

    music_cfg = config.get(
        "music",
        {},
    )

    music_controller = None
    music_library = None
    music_prewarm_thread = None
    music_playing = False
    goodbye_reply_index = 0

    if bool(
        music_cfg.get(
            "enabled",
            False,
        )
    ):
        music_provider = str(
            music_cfg.get(
                "provider",
                "qqmusic",
            )
        ).strip().lower()

        if music_provider not in {"qqmusic", "http"}:
            print(
                "[MUSIC] INIT_ERROR "
                f"unsupported provider="
                f"{music_provider}",
                flush=True,
            )
        elif music_provider == "qqmusic":
            repo_root = (
                Path(__file__)
                .resolve()
                .parents[2]
            )

            profile_path = Path(
                str(
                    music_cfg.get(
                        "profile_path",
                        (
                            "private/"
                            "qqmusic-firefox"
                        ),
                    )
                )
            ).expanduser()

            if not profile_path.is_absolute():
                profile_path = (
                    repo_root
                    / profile_path
                )

            music_controller = (
                QQMusicController(
                    profile_path=(
                        profile_path
                    ),
                    firefox_binary=str(
                        music_cfg.get(
                            "firefox_binary",
                            "/usr/bin/firefox",
                        )
                    ),
                    geckodriver_path=str(
                        music_cfg.get(
                            "geckodriver_path",
                            "/usr/local/bin/geckodriver",
                        )
                    ),
                    headless=bool(
                        music_cfg.get(
                            "headless",
                            True,
                        )
                    ),
                    timeout_seconds=float(
                        music_cfg.get(
                            "timeout_seconds",
                            30.0,
                        )
                    ),
                    speaker_match_any=list(
                        audio_cfg[
                            "speaker"
                        ][
                            "match_any"
                        ]
                    ),
                )
            )

            print(
                "[INIT] QQ Music "
                "controller ready "
                f"profile={profile_path}",
                flush=True,
            )

            music_library = (
                QQMusicPersonalLibrary(
                    music_controller,
                    cache_path=(
                        repo_root
                        / "private"
                        / "qqmusic-library.json"
                    ),
                )
            )

            cached_playlists = (
                music_library.data.get(
                    "playlists",
                    {},
                )
            )

            cached_song_rows = sum(
                len(
                    playlist.get(
                        "songs",
                        [],
                    )
                )
                for playlist
                in cached_playlists.values()
            )

            print(
                "[INIT] Personal music "
                "library ready "
                f"playlists="
                f"{len(cached_playlists)} "
                f"song_rows="
                f"{cached_song_rows}",
                flush=True,
            )

            if bool(
                music_cfg.get(
                    "prewarm",
                    True,
                )
            ):
                def _prewarm_music():
                    t0 = time.monotonic()

                    print(
                        "[MUSIC] PREWARM_START",
                        flush=True,
                    )

                    try:
                        status = (
                            music_controller
                            .prewarm()
                        )

                    except Exception as exc:
                        print(
                            "[MUSIC] PREWARM_ERROR "
                            f"{type(exc).__name__}: "
                            f"{exc}",
                            flush=True,
                        )

                    else:
                        print(
                            "[MUSIC] PREWARM_OK "
                            f"seconds="
                            f"{time.monotonic() - t0:.3f} "
                            f"status={status}",
                            flush=True,
                        )

                        if (
                            music_library
                            is None
                        ):
                            return

                        refresh_enabled = bool(
                            music_cfg.get(
                                "library_refresh_enabled",
                                True,
                            )
                        )

                        if not refresh_enabled:
                            print(
                                "[MUSIC] "
                                "PERSONAL_REFRESH_DISABLED",
                                flush=True,
                            )
                            return

                        try:
                            refresh_interval = float(
                                music_cfg.get(
                                    "library_refresh_interval_seconds",
                                    3600.0,
                                )
                            )
                        except (
                            TypeError,
                            ValueError,
                        ):
                            refresh_interval = 3600.0

                        print(
                            "[MUSIC] "
                            "PERSONAL_REFRESH_BACKGROUND "
                            f"interval="
                            f"{refresh_interval:.0f}s",
                            flush=True,
                        )

                        while True:
                            refresh_t0 = (
                                time.monotonic()
                            )

                            print(
                                "[MUSIC] "
                                "PERSONAL_REFRESH_START",
                                flush=True,
                            )

                            try:
                                refreshed = (
                                    music_library
                                    .refresh_all()
                                )

                            except Exception as exc:
                                print(
                                    "[MUSIC] "
                                    "PERSONAL_REFRESH_ERROR "
                                    f"{type(exc).__name__}: "
                                    f"{exc}",
                                    flush=True,
                                )

                            else:
                                playlists = (
                                    refreshed.get(
                                        "playlists",
                                        {},
                                    )
                                )

                                song_rows = sum(
                                    len(
                                        item.get(
                                            "songs",
                                            [],
                                        )
                                    )
                                    for item
                                    in playlists.values()
                                )

                                print(
                                    "[MUSIC] "
                                    "PERSONAL_REFRESH_OK "
                                    f"seconds="
                                    f"{time.monotonic() - refresh_t0:.3f} "
                                    f"playlists="
                                    f"{len(playlists)} "
                                    f"song_rows="
                                    f"{song_rows}",
                                    flush=True,
                                )

                            # <= 0 means refresh once
                            # after prewarm, then stop.
                            if (
                                refresh_interval
                                <= 0
                            ):
                                break

                            time.sleep(
                                max(
                                    60.0,
                                    refresh_interval,
                                )
                            )


                music_prewarm_thread = (
                    threading.Thread(
                        target=_prewarm_music,
                        name="qqmusic-prewarm",
                        daemon=True,
                    )
                )

                music_prewarm_thread.start()

    project_root = Path(__file__).resolve().parents[2]
    tools_path = project_root / "configs/tools.yaml"
    tools_config = load_config(tools_path) if tools_path.exists() else {}
    music_http_cfg = tools_config.get("music_http", {})
    music_cfg["http"] = music_http_cfg
    preferences_path = project_root / str(
        music_http_cfg.get("preferences_path", "configs/music_preferences.yaml"))
    if preferences_path.exists():
        music_cfg["preferences"] = load_config(preferences_path).get("random_play", {})
    device_volume = PulseVolumeController(
        speaker_match_any=list(audio_cfg["speaker"]["match_any"]),
        step_percent=10, max_percent=100)
    music_tools = MusicTools(music_cfg, music_controller, music_library,
                             player=DirectAudioPlayer(device_volume.sink_name))
    fan_light = None
    try:
        fan_light = FanLightController()
        fan_status = fan_light.initialize()
        print(f"[FAN_LIGHT] initialized {fan_status}", flush=True)
    except Exception as exc:
        print(f"[FAN_LIGHT] unavailable: {type(exc).__name__}: {exc}", flush=True)
        if fan_light is not None:
            fan_light.close()
        fan_light = None
    local_tools = build_edge_tools(device_volume, music_tools, fan_light, display_light)

    auth_bridge.QR_IMAGE.unlink(missing_ok=True)
    auth_bridge.BROWSER_IMAGE.unlink(missing_ok=True)
    auth_bridge.AVATAR_IMAGE.unlink(missing_ok=True)
    auth_bridge.publish("unknown")
    auth_request_id = auth_bridge.read_json(auth_bridge.REQUEST).get("id", "")
    music_control_request_id = control_bridge.read_json(control_bridge.REQUEST).get("id", "")
    auth_thread = None
    library_refresh_thread = None
    library_refresh_generation = None

    def refresh_personal_library_after_login():
        nonlocal library_refresh_thread, library_refresh_generation
        if music_library is None or not music_cfg.get("library_refresh_on_login", True):
            return
        if (library_refresh_thread is not None and library_refresh_thread.is_alive()
                and library_refresh_generation == music_library.generation):
            return

        def refresh():
            try:
                print("[MUSIC] PERSONAL_REFRESH_LOGIN_START", flush=True)
                data = music_library.refresh_all()
                playlists = data.get("playlists", {})
                songs = sum(len(item.get("songs", [])) for item in playlists.values())
                print(f"[MUSIC] PERSONAL_REFRESH_LOGIN_OK playlists={len(playlists)} songs={songs}",
                      flush=True)
            except Exception as exc:
                print(f"[MUSIC] PERSONAL_REFRESH_LOGIN_ERROR type={type(exc).__name__}: {exc}",
                      flush=True)

        library_refresh_generation = music_library.generation
        library_refresh_thread = threading.Thread(target=refresh, daemon=True,
                                                   name="qqmusic-library-login-refresh")
        library_refresh_thread.start()

    def run_music_auth(action: str):
        auth_bridge.publish("logging_out" if action == "logout" else "checking"
                            if action == "check" else "starting")
        try:
            if not isinstance(music_controller, QQMusicController):
                raise QQMusicError("当前未使用 QQ 音乐网页播放器")
            if action == "logout":
                music_controller.logout_account()
                if music_library is not None:
                    music_library.clear_cache()
                auth_bridge.QR_IMAGE.unlink(missing_ok=True)
                auth_bridge.AVATAR_IMAGE.unlink(missing_ok=True)
                auth_bridge.publish("required")
            else:
                if action == "login":
                    if not music_controller.authenticate_with_browser(
                            auth_bridge.BROWSER_IMAGE, auth_bridge.publish,
                            lambda: auth_bridge.read_json(auth_bridge.BROWSER_CLICK),
                            lambda: auth_bridge.read_json(auth_bridge.BROWSER_CANCEL),
                            auth_bridge.QR_IMAGE):
                        return
                account = music_controller.account_info(auth_bridge.AVATAR_IMAGE)
                auth_bridge.publish(account["state"], nickname=account["nickname"],
                                    avatar=account["avatar"])
                if account["state"] == "ready":
                    if action == "login" and music_library is not None:
                        music_library.clear_cache()
                    refresh_personal_library_after_login()
        except Exception as exc:
            auth_bridge.QR_IMAGE.unlink(missing_ok=True)
            auth_bridge.BROWSER_IMAGE.unlink(missing_ok=True)
            auth_bridge.publish("error", detail=str(exc)[:160])
            print(f"[MUSIC] QQ_AUTH_ERROR type={type(exc).__name__}", flush=True)

    def poll_music_login():
        nonlocal auth_request_id, auth_thread
        request = auth_bridge.read_json(auth_bridge.REQUEST)
        request_id = request.get("id", "")
        if not request_id or request_id == auth_request_id:
            return
        if auth_thread is not None and auth_thread.is_alive():
            return
        auth_request_id = request_id
        action = request.get("action", "login")
        if action not in {"login", "logout", "check"}:
            return
        auth_thread = threading.Thread(target=run_music_auth, args=(action,), daemon=True,
                                       name="qqmusic-auth")
        auth_thread.start()

    if isinstance(music_controller, QQMusicController):
        auth_thread = threading.Thread(target=run_music_auth, args=("check",),
                                       daemon=True, name="qqmusic-auth-check")
        auth_thread.start()

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

    ack_enabled = bool(tts_cfg.get("acknowledgement_enabled", True))
    ack_clips = {}
    wake_reply_sent = False
    wake_reply_index = 0

    if tts_enabled:
        provider = str(
            tts_cfg.get(
                "provider",
                "kokoro",
            )
        ).strip().lower()

        if provider not in {"kokoro", "edge"}:
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

                for action, phrase in ALL_PHRASES.items():
                    try:
                        cached = cache_path(tts_cfg.get("edge_voice", "zh-CN-XiaoxiaoNeural"), phrase)
                        if provider == "edge" and valid_clip(cached):
                            ack_clips[action] = cached
                            print(f"[CACHE] EDGE_READY action={action}", flush=True)
                            continue
                        path = Path("/dev/shm") / f"luckrobot_ack_{action}.wav"
                        print(f"[CACHE] LOCAL_FALLBACK action={action}", flush=True)
                        chunk = tts._generate(phrase)
                        tts._write_wav(path, chunk.samples, chunk.sample_rate)
                        ack_clips[action] = path
                    except Exception as exc:
                        print(f"[ACK] INIT_ERROR action={action} error={type(exc).__name__}", flush=True)
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

                if provider == "edge":
                    from edge.audio.tts.edge_online import EdgeOnlineTts
                    tts = EdgeOnlineTts(tts_cfg, tts)
                    print(f"[INIT] Edge TTS ready voice={tts.voice} fallback=kokoro", flush=True)

                tts.playback_observer = display_voice_playing
                if provider == "edge":
                    tts.fallback.playback_observer = display_voice_playing

            except TtsError as exc:
                print(
                    "[TTS] INIT_ERROR "
                    f"{exc}",
                    flush=True,
                )

                tts = None

    from edge.audio.direction import DirectionMonitor
    direction_monitor = DirectionMonitor(audio_cfg.get("sound_direction", {}))

    acknowledgements = ToolAcknowledgement(
        {k: v for k, v in ack_clips.items() if k in PHRASES} if ack_enabled else {}, "<unavailable>",
        delay_seconds=float(tts_cfg.get("acknowledgement_delay_seconds", 0.35)),
        dynamic_synth=(getattr(tts, "prepare_online", None)
                       if tts_cfg.get("dynamic_music_acknowledgement_enabled", True) else None),
        dynamic_wait_seconds=float(tts_cfg.get("dynamic_music_acknowledgement_wait_seconds", 1.5)))
    music_tools.before_playback = acknowledgements.finish

    def pause_music_for_conversation(reason):
        nonlocal music_playing
        try:
            paused = music_tools.pause_for_conversation()
            music_playing = paused["playing"]
            display_music(paused.get("music"), playing=music_playing)
            print(f"[MUSIC] WAKE_PAUSED reason={reason}", flush=True)
            return True
        except Exception as exc:
            print(f"[MUSIC] WAKE_PAUSE_FAILED reason={reason} type={type(exc).__name__}", flush=True)
            display_state("error", "音乐未能暂停，请先手动暂停音乐")
            return False

    if agent_client is not None:
        agent_client.on_event = acknowledgements.on_event

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
            post_kws_transcript_aliases=(
                wake_cfg.get(
                    "post_kws_transcript_aliases",
                    [],
                )
            ),
            include_pre_wake_speech=bool(wake_cfg.get("include_pre_wake_speech", False)),
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

    conversation_log = ConversationLog(
        interaction_cfg.get("conversation_log", {})
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

    print(
        "[MUSIC] PREWARM_BACKGROUND",
        flush=True,
    )

    music_metadata_stop = threading.Event()
    def watch_qq_track():
        while not music_metadata_stop.wait(1.5):
            if not music_tools.playing or not isinstance(music_controller, QQMusicController):
                continue
            try:
                track, cover_revision = music_controller.current_track_snapshot(MUSIC_COVER_IMAGE)
                advanced = music_tools.advance_playlist_if_needed(track)
                if advanced is not None:
                    display_music(advanced.get("music"), playing=music_tools.playing)
                    continue
                current = music_tools.refresh_current_track(track)
                if cover_revision and music_tools.current_song is not None:
                    if music_tools.current_song.get("cover_revision") != cover_revision:
                        music_tools.current_song["cover_revision"] = cover_revision
                        current = dict(music_tools.current_song)
                lyrics = music_controller.current_lyrics_snapshot()
                if lyrics and music_tools.current_song is not None:
                    if any(music_tools.current_song.get(key) != value
                           for key, value in lyrics.items()):
                        music_tools.current_song.update(lyrics)
                        current = dict(music_tools.current_song)
                if current is not None:
                    display_music(current, playing=music_tools.playing)
            except Exception as exc:
                print(f"[MUSIC] TRACK_POLL_FAILED error={type(exc).__name__}", flush=True)
    if music_controller is not None:
        threading.Thread(target=watch_qq_track, name="qq-track-display", daemon=True).start()

    state = None
    from edge.navigation.feedback import FeedbackSpeech
    navigation_feedback = FeedbackSpeech()

    try:
        if audio_cfg.get("sound_direction", {}).get("enabled", False):
            direction_monitor.start()
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
                        poll_music_login()
                        notice = navigation_feedback.take(
                            ready=interaction_gate.state == InteractionGate.SLEEPING and not music_playing)
                        if notice:
                            capture.stop()
                            try:
                                print(f"[NAVIGATION_FEEDBACK] {notice}", flush=True)
                                display_state("speaking", notice)
                                acknowledgements.finish()
                                tts.speak(notice, speaker)
                            except Exception as exc:
                                print(f"[NAVIGATION_FEEDBACK] failed={type(exc).__name__}", flush=True)
                            finally:
                                display_state("sleeping", "等待 Lucky")
                                capture.start()
                            continue
                        control_request = control_bridge.read_json(control_bridge.REQUEST)
                        control_id = control_request.get("id", "")
                        if control_id and control_id != music_control_request_id:
                            music_control_request_id = control_id
                            action = control_request.get("action")
                            if action in control_bridge.ACTIONS:
                                try:
                                    control_result = music_tools.control(action)
                                except Exception as exc:
                                    print(f"[MUSIC] TOUCH_CONTROL_ERROR action={action} "
                                          f"type={type(exc).__name__}", flush=True)
                                    control_result = {"ok": False, "message": "播放器暂时无法执行操作。",
                                                      "playing": music_playing}
                                music_playing = control_result.get("playing", music_playing)
                                if control_result.get("ok") and "music" in control_result:
                                    display_music(control_result["music"],
                                                  playing=music_playing)
                                    if control_result["music"] is not None:
                                        display_state("music", "等待 Lucky")
                                    else:
                                        display_state("sleeping", "等待 Lucky")
                                control_bridge.publish(control_id, action, control_result)
                                print(f"[MUSIC] TOUCH_CONTROL action={action} "
                                      f"ok={control_result.get('ok')} playing={music_playing}",
                                      flush=True)
                        if (
                            music_playing
                            and music_tools.playback_finished()
                        ):
                            music_playing = False
                            display_music(None)
                            print(
                                "[MUSIC] PLAYBACK_FINISHED",
                                flush=True,
                            )
                            print(
                                "[STATE] SLEEPING reason=music_finished",
                                flush=True,
                            )

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
                                conversation_log.write("KWS", keyword, state="sleeping")
                                wake_reply_sent = False
                                pause_music_for_conversation("kws")

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

                        if vad.is_speech_detected:
                            interaction_gate.note_speech_activity(now)
                        elif not vad.has_segment() and interaction_gate.expire_if_needed(now):
                            music_tools.clear_pending()
                            print("[STATE] SLEEPING reason=timeout", flush=True)
                            if agent_client is not None:
                                print("[AGENT_MEMORY] PRESERVED "
                                      f"reason=interaction_timeout messages={agent_client.history_messages}",
                                      flush=True)
                            if wake_kws:
                                wake_stream = wake_kws.create_stream()

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

                            sleeping_segment = (
                                wake_enabled
                                and interaction_gate.state == InteractionGate.SLEEPING
                            )

                            # Optional diagnostics transcribe sleeping speech but
                            # never use the transcript to wake or execute commands.
                            if sleeping_segment and not conversation_log.log_sleeping_asr:
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

                            if sleeping_segment:
                                text = (
                                    asr.transcribe(
                                        asr_samples,
                                        sample_rate,
                                    )
                                )
                            else:
                                begin_turn()
                                record("vad_buffer_after_segment", vad.last_endpoint_buffer_seconds)
                                status("声音转文字 / ASR")
                                display_state("transcribing", "正在识别")
                                with measure("asr"):
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
                                if not sleeping_segment:
                                    display_state("listening", "我在听" if
                                                  interaction_gate.state == InteractionGate.AWAKE_WAIT_COMMAND
                                                  else "等待下一句话")
                                continue

                            conversation_log.write(
                                "ASR_SLEEP" if sleeping_segment else "ASR",
                                text,
                                duration=f"{duration_sec:.2f}s",
                                inference=f"{elapsed:.3f}s",
                            )

                            print(
                                "[ASR] "
                                f"start={start_sec:.2f}s "
                                f"duration={duration_sec:.2f}s "
                                f"inference={elapsed:.3f}s"
                            )

                            if debug_log_transcript:
                                print(
                                    ("[ASR_SLEEP_TEXT] " if sleeping_segment else "[ASR_TEXT] ")
                                    +
                                    f"{text}",
                                    flush=True,
                                )

                            if sleeping_segment:
                                continue

                            decision = (
                                interaction_gate
                                .process(
                                    text,
                                    now=time.monotonic(),
                                    defer_timeout=True,
                                )
                            )

                            if decision.action == "ignore" and decision.reason == "wake_echo_fragment":
                                print(f"[GATE] IGNORE reason={decision.reason} text={text!r}", flush=True)
                            if decision.action == "ignore":
                                display_state("listening", "我在听" if
                                              interaction_gate.state == InteractionGate.AWAKE_WAIT_COMMAND
                                              else "等待下一句话")

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
                                if not pause_music_for_conversation("wake_reply"):
                                    continue
                                if not wake_reply_sent:
                                    wake_reply_sent = True
                                    names = list(WAKE_PHRASES)
                                    clip = ack_clips.get(names[wake_reply_index % len(names)])
                                    wake_reply_index += 1
                                    if clip is not None and speaker != "<unavailable>":
                                        capture.stop()
                                        try:
                                            acknowledgements.finish()
                                            print("[WAKE] LOCAL_REPLY cached=true", flush=True)
                                            play_cached_reply(clip, speaker, display_voice_playing)
                                            time.sleep(post_playback_guard_seconds)
                                        except (OSError, subprocess.SubprocessError) as exc:
                                            print(f"[WAKE] REPLY_ERROR {type(exc).__name__}", flush=True)
                                        finally:
                                            vad = create_vad(vad_cfg, sample_rate)
                                            zero_audio_samples = 0
                                            interaction_gate.on_wake(time.monotonic())
                                            capture.start()
                                print(
                                    "[STATE] "
                                    "AWAKE_WAIT_COMMAND",
                                    flush=True,
                                )

                            elif (
                                decision.action
                                == "sleep"
                            ):
                                music_tools.clear_pending()
                                acknowledgements.finish()
                                names = list(GOODBYE_PHRASES)
                                clip = ack_clips.get(names[goodbye_reply_index % len(names)])
                                goodbye_reply_index += 1
                                if clip is not None and speaker != "<unavailable>":
                                    capture.stop()
                                    try:
                                        play_cached_reply(clip, speaker, display_voice_playing)
                                    except (OSError, subprocess.SubprocessError) as exc:
                                        print(f"[GOODBYE] REPLY_ERROR {type(exc).__name__}", flush=True)
                                    finally:
                                        capture.start()
                                vad = create_vad(vad_cfg, sample_rate)
                                zero_audio_samples = 0
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

                                print('[WAKE] Waiting for "Lucky".', flush=True)

                                if wake_kws:
                                    wake_stream = (
                                        wake_kws
                                        .create_stream()
                                    )

                            elif (
                                decision.action
                                == "command"
                            ):
                                if not pause_music_for_conversation("command"):
                                    continue
                                conversation_log.write("USER", decision.command)
                                display_dialogue(
                                    user_text=decision.command,
                                    assistant_text="",
                                    assistant_progress_chars=0)
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

                                volume_command = (
                                    parse_volume_command(
                                        decision.command
                                        or ""
                                    )
                                )

                                if needs_semantic_route(decision.command or ""):
                                    volume_command = None

                                if (
                                    volume_command
                                    is not None
                                ):
                                    volume_t0 = (
                                        time.monotonic()
                                    )

                                    print(
                                        "[STATE] "
                                        "LOCAL_CONTROL",
                                        flush=True,
                                    )

                                    # Same half-duplex policy
                                    # as normal Agent replies.
                                    with measure("capture_stop"):
                                        capture.stop()

                                    playback_happened = (
                                        False
                                    )

                                    try:
                                        volume_args = {"action": volume_command.action}
                                        if volume_command.percent is not None:
                                            volume_args["percent"] = volume_command.percent
                                        local_result = local_tools.execute("volume_control", volume_args)
                                        local_reply = local_result["message"]

                                        print(
                                            "[LOCAL_REPLY] "
                                            f"{local_reply}",
                                            flush=True,
                                        )

                                        if (
                                            tts is not None
                                            and speaker
                                            != "<unavailable>"
                                        ):
                                            print(
                                                "[STATE] "
                                                "SPEAKING",
                                                flush=True,
                                            )

                                            acknowledgements.finish()
                                            with measure("tts_total"):
                                                tts_result = (
                                                    tts.speak(
                                                        local_reply,
                                                        speaker,
                                                    )
                                                )

                                            playback_happened = (
                                                True
                                            )

                                            print(
                                                "[TTS] OK "
                                                f"speaker_id="
                                                f"{tts.speaker_id} "
                                                f"generation="
                                                f"{tts_result.generation_seconds:.3f}s "
                                                f"audio="
                                                f"{tts_result.audio_seconds:.3f}s "
                                                f"sample_rate="
                                                f"{tts_result.sample_rate}",
                                                flush=True,
                                            )

                                        elif (
                                            tts is not None
                                            and speaker == "<unavailable>"
                                        ):
                                            print(
                                                "[TTS] ERROR "
                                                "speaker "
                                                "unavailable",
                                                flush=True,
                                            )

                                        print(
                                            "[LATENCY] "
                                            "volume="
                                            f"{time.monotonic() - volume_t0:.3f}s",
                                            flush=True,
                                        )

                                    except (
                                        PulseVolumeError,
                                        TtsError,
                                    ) as exc:
                                        print(
                                            "[VOLUME] ERROR "
                                            f"{type(exc).__name__}: "
                                            f"{exc}",
                                            flush=True,
                                        )

                                    finally:
                                        # Clean local turn
                                        # exactly like a spoken
                                        # Agent turn.
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
                                            "[STATE] "
                                            "LISTENING",
                                            flush=True,
                                        )

                                        capture.start()

                                elif (
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
                                        with measure("vision_snapshot"):
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
                                    with measure("capture_stop"):
                                        capture.stop()

                                    acknowledgements.sink = speaker
                                    acknowledgements.begin_turn(decision.command or "")

                                    turn_monitor = None
                                    turn_stream_speaker = None
                                    turn_display_reply = ""
                                    if wake_kws and wake_cfg.get("barge_in_enabled", False):
                                        try:
                                            turn_monitor = WakeInterruptMonitor(
                                                capture, wake_kws,
                                                on_wake=lambda: pause_music_for_conversation("monitor")
                                            ).start()
                                        except Exception as exc:
                                            print(f"[BARGE_IN] UNAVAILABLE error={type(exc).__name__}", flush=True)

                                    if (
                                        turn_monitor is not None
                                        and tts is not None
                                        and speaker != "<unavailable>"
                                        and agent_bridge_cfg.get("stream_text_to_tts", False)
                                    ):
                                        turn_stream_speaker = StreamingReplySpeaker(
                                            tts, speaker, turn_monitor.cancellation,
                                            before_playback=acknowledgements.finish,
                                            on_text_progress=lambda chars: display_dialogue(
                                                assistant_progress_chars=chars),
                                            max_workers=tts_cfg.get(
                                                "stream_prefetch_workers", 3),
                                            fallback_grace_seconds=tts_cfg.get(
                                                "stream_fallback_grace_seconds", 0.35))

                                    def on_turn_event(event):
                                        nonlocal turn_display_reply
                                        acknowledgements.on_event(event)
                                        if turn_stream_speaker is not None:
                                            if event.get("type") == "text_delta":
                                                status("文字转声音 / speak")
                                                turn_display_reply += event.get("text", "")
                                                display_state("speaking", "正在回答")
                                                display_dialogue(
                                                    assistant_text=turn_display_reply)
                                            turn_stream_speaker.on_event(event)

                                    agent_client.on_event = on_turn_event

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
                                            with measure("identity"):
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
                                    turn_memory_recorded = False

                                    try:
                                        agent_t0 = time.monotonic()

                                        command_text = (
                                            decision.command
                                            or ""
                                        )
                                        model_command_text = (
                                            decision.command_for_model
                                            or command_text
                                        )

                                        fast_path_request = (
                                            infer_explicit_vision_fast_path(
                                                command_text
                                            )
                                            if turn_vision_snapshot
                                            is not None
                                            else None
                                        )

                                        fast_path_frames = None

                                        if (
                                            fast_path_request
                                            is not None
                                            and
                                            turn_vision_snapshot
                                            is not None
                                        ):
                                            try:
                                                with measure("vision_select"):
                                                    fast_path_frames = (
                                                        select_turn_snapshot_frames(
                                                            turn_vision_snapshot,
                                                            fast_path_request,
                                                        )
                                                    )
                                            except VisionSelectionError:
                                                # Fall back to the normal
                                                # model-driven route if the
                                                # frozen turn snapshot cannot
                                                # satisfy this fast path.
                                                fast_path_request = None

                                        compound_request = needs_semantic_route(command_text)
                                        if compound_request:
                                            fast_path_request = None
                                        local_request = (None if compound_request
                                                         else music_tools.local_request(command_text))
                                        status("本地处理音乐" if local_request is not None else "思考 / 模型处理中")
                                        display_state(
                                            "thinking",
                                            "正在处理音乐" if local_request is not None else "想一想")
                                        if local_request is not None:
                                            agent_reply = AgentReply(text="", model="local-music", tool_request=local_request)
                                        elif (
                                            fast_path_request
                                            is not None
                                            and fast_path_frames
                                        ):
                                            acknowledgements.on_event(
                                                {"type": "tool_start", "action": "request_vision"})
                                            fast_path_tool_mode = (
                                                explicit_vision_fast_path_tool_mode(
                                                    command_text
                                                )
                                            )

                                            print(
                                                "[VISION] FAST_PATH "
                                                f"mode={fast_path_request.mode} "
                                                f"count={len(fast_path_frames)} "
                                                f"tools={fast_path_tool_mode}",
                                                flush=True,
                                            )

                                            agent_reply = (
                                                agent_client
                                                .chat(
                                                    model_command_text,
                                                    jpeg_frames=[
                                                        frame.jpeg_bytes
                                                        for frame
                                                        in fast_path_frames
                                                    ],
                                                    local_identity=(
                                                        turn_identity_state
                                                    ),
                                                    tool_mode=(
                                                        fast_path_tool_mode
                                                    ),
                                                    cancellation=(
                                                        turn_monitor.cancellation
                                                        if turn_monitor is not None
                                                        else None
                                                    ),
                                                )
                                            )

                                        else:
                                            music_candidates = music_tools.pending_context()
                                            if music_candidates:
                                                print("[MUSIC] ROUTE_CANDIDATES " + json.dumps(
                                                    music_candidates, ensure_ascii=False,
                                                    separators=(',', ':')), flush=True)
                                            agent_reply = (
                                                agent_client
                                                .chat(
                                                    model_command_text,
                                                    local_identity=(
                                                        turn_identity_state
                                                    ),
                                                    music_candidates=music_candidates,
                                                    cancellation=(
                                                        turn_monitor.cancellation
                                                        if turn_monitor is not None
                                                        else None
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

                                            acknowledgements.on_event(
                                                {"type": "tool_start", "action": "request_vision"})
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

                                            with measure("vision_select"):
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
                                                    model_command_text,
                                                    jpeg_frames=[
                                                        frame
                                                        .jpeg_bytes
                                                        for frame
                                                        in frames
                                                    ],
                                                    local_identity=(
                                                        turn_identity_state
                                                    ),
                                                    cancellation=(
                                                        turn_monitor.cancellation
                                                        if turn_monitor is not None
                                                        else None
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

                                        if agent_reply.tool_requests:
                                            token = turn_monitor.cancellation if turn_monitor else None
                                            plan = list(agent_reply.tool_requests)
                                            if token is not None:
                                                token.check()
                                            if any(item["name"] == "music_search" for item in plan):
                                                acknowledgements.on_event(
                                                    {"type": "tool_start", "action": "play_music"})

                                            def execute_action(name, arguments):
                                                if name in REMOTE_SCHEMAS:
                                                    return agent_client.execute_remote_tool(name, arguments, token)
                                                return local_tools.execute(name, arguments)

                                            music_plan = [item for item in plan if item["name"].startswith("music_")]
                                            other_plan = [item for item in plan if not item["name"].startswith("music_")]
                                            if music_plan and other_plan:
                                                # Validate the complete batch before any side effects.
                                                from robot_tools.batch import validate_plan
                                                validate_plan(plan)
                                                results = execute_plan(other_plan, execute_action, token)
                                                spoken = " ".join(result_message(item) for item in results)
                                                if token is not None:
                                                    token.check()
                                                acknowledgements.finish()
                                                display_dialogue(assistant_text=spoken)
                                                display_state("speaking", "文字转声音 / speak")
                                                tts.speak(spoken, speaker)
                                                if token is not None:
                                                    token.check()
                                                results += execute_plan(music_plan, execute_action, token)
                                            else:
                                                results = execute_plan(plan, execute_action, token)
                                            messages = [result_message(item) for item in results]
                                            batch_reply = " ".join(messages)
                                            for item in results:
                                                if "playing" in item:
                                                    music_playing = item["playing"]
                                                if "music" in item:
                                                    display_music(item["music"], playing=music_playing)
                                                print("[TOOL_RESULT] " + json.dumps({
                                                    "tool": item["tool"], "ok": item.get("ok"),
                                                    "status": item.get("status"), "message": result_message(item)
                                                }, ensure_ascii=False), flush=True)
                                            agent_client.record_completed_turn(command_text, batch_reply)
                                            turn_memory_recorded = True
                                            agent_reply = AgentReply(text=batch_reply, model="local-tool",
                                                                     end_conversation=agent_reply.end_conversation)
                                            if token is not None:
                                                token.check()
                                            if music_playing:
                                                conversation_log.write("ASSISTANT", batch_reply, model="local-tool")
                                                display_dialogue(assistant_text=batch_reply)
                                                interaction_gate.reset()
                                                music_tools.clear_pending()
                                                if wake_kws:
                                                    wake_stream = wake_kws.create_stream()
                                                print("[STATE] SLEEPING reason=music_playback", flush=True)
                                                continue

                                        tool_request = agent_reply.tool_request
                                        if agent_reply.music_request is not None:
                                            request = agent_reply.music_request
                                            if request.action == "play_music":
                                                if has_explicit_music_intent(command_text):
                                                    tool_request = {"name": "music_search",
                                                        "arguments": {"query": request.query, "utterance": command_text}}
                                                else:
                                                    print(
                                                        "[MUSIC] ROUTE_REJECTED "
                                                        "reason=missing_explicit_cue",
                                                        flush=True,
                                                    )
                                                    tool_request = None
                                                    agent_reply = AgentReply(
                                                        text="我没听清，能再说一遍吗？",
                                                        model="local-music-guard",
                                                    )
                                            elif request.action == "recommend_music":
                                                tool_request = {"name": "music_search",
                                                    "arguments": {"query": "推荐", "utterance": command_text}}
                                            elif request.action == "select_music":
                                                tool_request = {"name": "music_select",
                                                    "arguments": {"selection": request.query}}
                                            else:
                                                tool_request = {"name": "music_control",
                                                    "arguments": {"action": request.action}}
                                        if tool_request is not None:
                                            if turn_monitor is not None:
                                                turn_monitor.cancellation.check()
                                            tool_name = tool_request["name"]
                                            tool_source = (
                                                "local" if agent_reply.model == "local-music"
                                                else "model"
                                            )
                                            print(
                                                "[TOOL_REQUEST] "
                                                f"source={tool_source} name={tool_name} "
                                                f"arguments={json.dumps(tool_request['arguments'], ensure_ascii=False, separators=(',', ':'))}",
                                                flush=True,
                                            )
                                            if tool_name == "music_search":
                                                acknowledgements.on_event({"type": "tool_start", "action": "play_music"})
                                            tool_result = local_tools.execute(tool_name, tool_request["arguments"])
                                            if turn_monitor is not None:
                                                turn_monitor.cancellation.check()
                                            music_playing = tool_result.get("playing", music_playing)
                                            if "music" in tool_result:
                                                display_music(tool_result.get("music"),
                                                              playing=music_playing)
                                            agent_client.record_completed_turn(command_text, tool_result["message"])
                                            turn_memory_recorded = True
                                            agent_reply = AgentReply(text=tool_result["message"], model="local-tool")
                                            if music_playing:
                                                interaction_gate.reset()
                                                music_tools.clear_pending()
                                                if wake_kws:
                                                    wake_stream = wake_kws.create_stream()
                                                print("[STATE] SLEEPING reason=music_playback", flush=True)
                                                # Never speak final TTS on top of a playing song.
                                                continue

                                        if agent_reply.text:
                                            if (not agent_reply.end_conversation and
                                                    agent_reply.model not in {"local-music", "local-tool", "local-music-guard"}):
                                                music_tools.stage_suggested_songs(agent_reply.text)
                                            # Plain Cloud replies are archived by CloudAgentClient
                                            # before it returns. Local tool replies are marked above.
                                            turn_memory_recorded = True

                                        print(
                                            "[AGENT_REPLY] "
                                            f"{agent_reply.text}",
                                            flush=True,
                                        )
                                        conversation_log.write(
                                            "ASSISTANT", agent_reply.text,
                                            model=agent_reply.model)
                                        display_dialogue(assistant_text=agent_reply.text)

                                        print(
                                            "[AGENT] "
                                            f"model="
                                            f"{agent_reply.model}",
                                            flush=True,
                                        )

                                        streamed_reply = False
                                        if (
                                            turn_stream_speaker is not None
                                            and turn_stream_speaker.received_text
                                        ):
                                            streamed_reply = turn_stream_speaker.finish()
                                            if streamed_reply:
                                                display_dialogue(
                                                    assistant_progress_chars=len(agent_reply.text))
                                            playback_happened = (
                                                playback_happened or streamed_reply)

                                        if (
                                            tts is not None
                                            and speaker
                                            != "<unavailable>"
                                            and not streamed_reply
                                        ):
                                            print(
                                                "[STATE] SPEAKING",
                                                flush=True,
                                            )

                                            speech_scroller = SpokenTextScroller(
                                                agent_reply.text,
                                                lambda chars: display_dialogue(
                                                    assistant_progress_chars=chars))

                                            def on_speech_playback_begin():
                                                acknowledgements.finish()
                                                speech_scroller.start()

                                            try:
                                                with measure("tts_total"):
                                                    if turn_monitor is not None:
                                                        tts_result = tts.speak(
                                                            agent_reply.text, speaker,
                                                            before_playback=on_speech_playback_begin,
                                                            cancellation=turn_monitor.cancellation,
                                                        )
                                                    elif wake_kws and wake_cfg.get("barge_in_enabled", False):
                                                        tts_result = speak_with_wake(
                                                            tts, agent_reply.text, speaker,
                                                            capture=capture, kws=wake_kws,
                                                            before_playback=on_speech_playback_begin,
                                                        )
                                                    else:
                                                        tts_result = tts.speak(
                                                            agent_reply.text, speaker,
                                                            before_playback=on_speech_playback_begin,
                                                        )

                                                playback_happened = True
                                                display_dialogue(
                                                    assistant_progress_chars=len(agent_reply.text))

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

                                            except SpeechInterrupted:
                                                # Keep the just-announced music list: the
                                                # wake interruption may be the user's choice.
                                                interaction_gate.on_wake(time.monotonic())
                                                wake_stream = wake_kws.create_stream()
                                                wake_reply_sent = True
                                                playback_happened = True
                                                print("[BARGE_IN] Lucky detected; reply archived; speech stopped", flush=True)
                                                status("已打断，等待新命令")
                                                display_state("interrupted", "已打断，我在听")

                                            except TtsError as exc:
                                                print(
                                                    "[TTS] ERROR "
                                                    f"{exc}",
                                                    flush=True,
                                                )
                                            finally:
                                                speech_scroller.stop()

                                        elif (
                                            tts is not None
                                        ):
                                            print(
                                                "[TTS] ERROR "
                                                "speaker unavailable",
                                                flush=True,
                                            )

                                        if (agent_reply.end_conversation and
                                                interaction_gate.state == InteractionGate.ACTIVE):
                                            interaction_gate.reset()
                                            music_tools.clear_pending()
                                            if wake_kws:
                                                wake_stream = wake_kws.create_stream()
                                            print("[STATE] SLEEPING reason=model_end_conversation", flush=True)

                                    except (
                                        CloudAgentError,
                                        VisionSelectionError,
                                        QQMusicError,
                                    ) as exc:
                                        print(
                                            "[AGENT] ERROR "
                                            f"{exc}",
                                            flush=True,
                                        )
                                        failure_reply = ERROR_MESSAGES.get(
                                            getattr(exc, "reason", "unavailable"),
                                            ERROR_MESSAGES["unavailable"])
                                        status("模型服务暂时不可用")
                                        conversation_log.write("ASSISTANT", failure_reply,
                                                               model="local-error")
                                        display_dialogue(assistant_text=failure_reply)
                                        if tts is not None and speaker != "<unavailable>":
                                            try:
                                                print("[STATE] SPEAKING", flush=True)
                                                tts.speak(failure_reply, speaker,
                                                          before_playback=acknowledgements.finish,
                                                          cancellation=(turn_monitor.cancellation
                                                                        if turn_monitor else None))
                                                playback_happened = True
                                            except SpeechInterrupted:
                                                interaction_gate.on_wake(time.monotonic())
                                                wake_stream = wake_kws.create_stream() if wake_kws else None
                                                wake_reply_sent = True
                                            except Exception as tts_exc:
                                                print(f"[TTS] ERROR fallback={type(tts_exc).__name__}", flush=True)

                                    except SpeechInterrupted:
                                        pause_music_for_conversation("barge_in")
                                        if (
                                            wake_cfg.get("record_interrupted_turns", True)
                                            and not turn_memory_recorded
                                        ):
                                            agent_client.record_completed_turn(
                                                command_text,
                                                "【回复生成或播报时被用户用 Lucky 打断；模型输出已丢弃】",
                                            )
                                        # A new Lucky command may select from the list that
                                        # was being spoken when this turn was interrupted.
                                        interaction_gate.on_wake(time.monotonic())
                                        wake_stream = wake_kws.create_stream()
                                        wake_reply_sent = True
                                        playback_happened = True
                                        print("[BARGE_IN] Lucky detected; interrupted turn archived; output discarded", flush=True)
                                        conversation_log.write(
                                            "INTERRUPTED", command_text,
                                            output="discarded")
                                        status("已打断，等待新命令")
                                        display_state("interrupted", "已打断，我在听")

                                    except Exception as exc:
                                        print(
                                            "[AGENT] ERROR "
                                            f"{type(exc).__name__}: "
                                            f"{exc}",
                                            flush=True,
                                        )

                                    finally:
                                        if turn_stream_speaker is not None:
                                            if (
                                                turn_stream_speaker.received_text
                                                and not turn_stream_speaker.finished
                                                and turn_monitor is not None
                                            ):
                                                turn_monitor.cancellation.cancel()
                                            turn_stream_speaker.cancel()
                                        if turn_monitor is not None:
                                            turn_monitor.stop()
                                        agent_client.on_event = acknowledgements.on_event
                                        acknowledgements.finish()
                                        playback_happened = playback_happened or acknowledgements.played
                                        record("turn_until_reply_finished",
                                               time.monotonic() - turn_started.get())
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

                                        if interaction_gate.state == InteractionGate.SLEEPING:
                                            if music_playing:
                                                # Keep the music presentation active while
                                                # KWS remains the only accepted input.  A
                                                # generic wake-wait log would publish the
                                                # sleeping face and immediately overwrite it.
                                                print(
                                                    "[STATE] SLEEPING reason=music_playback",
                                                    flush=True,
                                                )
                                            else:
                                                print('[WAKE] Waiting for "Lucky".', flush=True)
                                        else:
                                            print("[STATE] LISTENING", flush=True)

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
        music_metadata_stop.set()
        direction_monitor.stop()
        music_tools.close()
        if fan_light is not None:
            fan_light.close()
        acknowledgements.finish()
        conversation_log.close()
        if music_controller is not None:
            music_controller.close()

            print(
                "[MUSIC] CONTROLLER_STOPPED",
                flush=True,
            )

        if vision_camera is not None:
            vision_camera.stop()

            print(
                "[VISION] CAMERA_STOPPED",
                flush=True,
            )


if __name__ == "__main__":
    main()
