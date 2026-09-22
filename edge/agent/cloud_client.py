from __future__ import annotations

import base64
import json
from shared.timing import trace_id, measure
from robot_tools.catalog import LOCAL_SCHEMAS
from robot_tools.registry import validate
from dataclasses import dataclass
from pathlib import Path
from urllib.error import (
    HTTPError,
    URLError,
)
from urllib.parse import urlsplit
from urllib.request import (
    Request,
    urlopen,
)

from edge.agent.memory_store import (
    ConversationMemory,
)


class CloudAgentError(RuntimeError):
    pass


@dataclass(frozen=True)
class VisionRequest:
    mode: str
    seconds: float
    count: int


@dataclass(frozen=True)
class MusicRequest:
    action: str
    query: str = ""


@dataclass(frozen=True)
class AgentReply:
    text: str
    model: str
    tool_request: dict | None = None
    vision_request: (
        VisionRequest | None
    ) = None
    music_request: (
        MusicRequest | None
    ) = None


class CloudAgentClient:
    def __init__(
        self,
        endpoint: str,
        timeout_seconds: float = 35.0,
        history_max_turns: int = 100,
        memory_db_path: str | Path = (
            "private/memory/"
            "conversation.sqlite3"
        ),
        compact_batch_turns: int = 100,
        archive_retrieval_limit: int = 6,
        progress_enabled: bool = False,
    ) -> None:
        self.endpoint = endpoint
        self.progress_enabled = progress_enabled
        self.on_event = None

        parsed = urlsplit(
            endpoint
        )

        path = parsed.path.rstrip("/")

        if path.endswith("/chat"):
            compact_path = (
                path[:-5]
                + "/compact"
            )
        else:
            compact_path = (
                path
                + "/compact"
            )

        self.compact_endpoint = (
            parsed._replace(
                path=compact_path
            ).geturl()
        )

        self.timeout_seconds = float(
            timeout_seconds
        )

        self.archive_retrieval_limit = max(
            1,
            int(
                archive_retrieval_limit
            ),
        )

        self.memory = ConversationMemory(
            memory_db_path,
            recent_turns=(
                history_max_turns
            ),
            compact_batch_turns=(
                compact_batch_turns
            ),
        )

    @property
    def history_turns(
        self,
    ) -> int:
        return self.memory.turn_count

    @property
    def history_messages(
        self,
    ) -> int:
        return (
            self.memory.turn_count
            * 2
        )

    def clear_memory(
        self,
    ) -> None:
        self.memory.clear()

    # Compatibility with the earlier
    # Phase 3.4 prototype.
    def reset_session(
        self,
    ) -> None:
        self.clear_memory()

    def record_completed_turn(
        self,
        user_text: str,
        assistant_text: str,
    ) -> None:
        user_text = str(
            user_text
        ).strip()

        assistant_text = str(
            assistant_text
        ).strip()

        if (
            not user_text
            or not assistant_text
        ):
            raise CloudAgentError(
                "Completed turn text "
                "must not be empty"
            )

        self.memory.add_turn(
            user_text,
            assistant_text,
        )

    def _post_chat(self, payload, cancellation=None):
        if cancellation is not None:
            cancellation.check()
        if not self.progress_enabled:
            if cancellation is None:
                return self._post_json(self.endpoint, payload)
            return self._post_json(self.endpoint, payload, cancellation)
        request = Request(
            self.endpoint.rstrip("/") + "/events",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Accept": "application/x-ndjson"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                if cancellation is not None:
                    cancellation.register_callback(response.close)
                for index in range(8192):
                    if cancellation is not None:
                        cancellation.check()
                    line = response.readline(131073)
                    if not line:
                        break
                    if len(line) > 131072:
                        raise CloudAgentError("Progress event exceeds size limit")
                    event = json.loads(line.decode("utf-8"))
                    if not isinstance(event, dict):
                        raise CloudAgentError("Progress event must be an object")
                    if event.get("type") == "result":
                        if not isinstance(event.get("data"), dict):
                            raise CloudAgentError("Invalid final response")
                        return event["data"]
                    if event.get("type") == "error":
                        raise CloudAgentError("Agent failed during progress request")
                    if event.get("type") == "timing":
                        print("[REMOTE_TIMING] " + json.dumps(event), flush=True)
                    elif event.get("type") in {"tool_start", "text_delta"} and self.on_event:
                        try:
                            self.on_event(event)
                        except Exception as exc:
                            print(f"[ACK] callback failed: {type(exc).__name__}", flush=True)
        except HTTPError as exc:
            if cancellation is not None:
                cancellation.check()
            if exc.code in {404, 405}:
                # Old API: no request was executed by this missing endpoint.
                if cancellation is None:
                    return self._post_json(self.endpoint, payload)
                return self._post_json(self.endpoint, payload, cancellation)
            raise CloudAgentError(f"Agent progress HTTP error {exc.code}") from exc
        except (OSError, ValueError) as exc:
            if cancellation is not None:
                cancellation.check()
            raise CloudAgentError("Invalid or interrupted Agent progress response") from exc
        if cancellation is not None:
            cancellation.check()
        raise CloudAgentError("Agent progress stream ended without a final result")

    def _post_json(
        self,
        endpoint: str,
        payload: dict,
        cancellation=None,
    ) -> dict:
        if cancellation is not None:
            cancellation.check()
        body = json.dumps(
            payload,
            ensure_ascii=False,
        ).encode("utf-8")

        request = Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": (
                    "application/json"
                ),
            },
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                if cancellation is not None:
                    cancellation.register_callback(response.close)
                response_body = (
                    response.read()
                )

        except HTTPError as exc:
            if cancellation is not None:
                cancellation.check()
            try:
                detail = (
                    exc.read()
                    .decode(
                        "utf-8",
                        errors="replace",
                    )
                )
            except Exception:
                detail = ""

            raise CloudAgentError(
                "Cloud Agent HTTP error "
                f"{exc.code}: "
                f"{detail[:500]}"
            ) from exc

        except URLError as exc:
            if cancellation is not None:
                cancellation.check()
            raise CloudAgentError(
                "Cloud Agent unavailable: "
                f"{exc.reason}"
            ) from exc

        except TimeoutError as exc:
            if cancellation is not None:
                cancellation.check()
            raise CloudAgentError(
                "Cloud Agent request timed out"
            ) from exc

        try:
            return json.loads(
                response_body.decode(
                    "utf-8"
                )
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise CloudAgentError(
                "Cloud Agent returned "
                "invalid JSON"
            ) from exc

    @staticmethod
    def _encode_jpeg_frames(
        jpeg_frames: list[bytes] | None,
    ) -> list[str]:
        frames = list(
            jpeg_frames
            or []
        )

        if len(frames) > 5:
            raise CloudAgentError(
                "At most 5 vision frames "
                "may be sent per request"
            )

        encoded_frames = []
        total_bytes = 0

        for index, frame in enumerate(
            frames
        ):
            if not isinstance(
                frame,
                (
                    bytes,
                    bytearray,
                ),
            ):
                raise CloudAgentError(
                    "Vision frame "
                    f"{index} is not bytes"
                )

            jpeg = bytes(
                frame
            )

            if (
                len(jpeg) < 4
                or jpeg[:2]
                != b"\xff\xd8"
                or jpeg[-2:]
                != b"\xff\xd9"
            ):
                raise CloudAgentError(
                    "Vision frame "
                    f"{index} is not "
                    "a complete JPEG"
                )

            if len(jpeg) > 2_000_000:
                raise CloudAgentError(
                    "Vision frame "
                    f"{index} exceeds "
                    "2 MB"
                )

            total_bytes += len(
                jpeg
            )

            if total_bytes > 5_000_000:
                raise CloudAgentError(
                    "Vision frame payload "
                    "exceeds 5 MB"
                )

            encoded_frames.append(
                base64.b64encode(
                    jpeg
                ).decode(
                    "ascii"
                )
            )

        return encoded_frames

    def _compact_pending(
        self,
        cancellation=None,
    ) -> None:
        while True:
            batch = (
                self.memory
                .get_compaction_batch()
            )

            if batch is None:
                return

            snapshot = (
                self.memory
                .prepare_context()
            )

            print(
                "[AGENT_MEMORY] COMPACT "
                f"turns="
                f"{batch.first_turn_id}-"
                f"{batch.last_turn_id}",
                flush=True,
            )

            compact_payload = {
                    "previous_summary": (
                        snapshot
                        .memory_summary
                    ),
                    "turns": (
                        batch.turns
                    ),
                }
            if cancellation is None:
                data = self._post_json(self.compact_endpoint, compact_payload)
            else:
                data = self._post_json(
                    self.compact_endpoint, compact_payload, cancellation)

            block_summary = str(
                data.get(
                    "block_summary",
                    "",
                )
            ).strip()

            cumulative_summary = str(
                data.get(
                    "cumulative_summary",
                    "",
                )
            ).strip()

            if (
                not block_summary
                or not cumulative_summary
            ):
                raise CloudAgentError(
                    "Compactor returned "
                    "an incomplete summary"
                )

            self.memory.save_compaction(
                batch,
                block_summary=(
                    block_summary
                ),
                cumulative_summary=(
                    cumulative_summary
                ),
            )

            print(
                "[AGENT_MEMORY] COMPACT_OK "
                f"through_turn="
                f"{batch.last_turn_id}",
                flush=True,
            )

    @staticmethod
    def _normalize_local_identity(
        local_identity: str,
    ) -> str:
        state = str(
            local_identity
        ).strip().lower()

        if state not in {
            "owner",
            "unknown",
            "uncertain",
        }:
            raise CloudAgentError(
                "local_identity must be "
                "owner, unknown, or uncertain"
            )

        return state

    def chat(
        self,
        text: str,
        jpeg_frames: list[bytes] | None = None,
        local_identity: str = "uncertain",
        tool_mode: str = "auto",
        cancellation=None,
    ) -> AgentReply:
        command = text.strip()

        if not command:
            raise CloudAgentError(
                "Agent command is empty"
            )

        local_identity = (
            self._normalize_local_identity(
                local_identity
            )
        )

        tool_mode = str(
            tool_mode
        ).strip().lower()

        if tool_mode not in {
            "auto",
            "none",
        }:
            raise CloudAgentError(
                "tool_mode must be "
                "auto or none"
            )

        images_jpeg_base64 = (
            self._encode_jpeg_frames(
                jpeg_frames
            )
        )

        try:
            with measure("memory_compact"):
                self._compact_pending(cancellation)
        except (
            CloudAgentError,
            RuntimeError,
            ValueError,
        ) as exc:
            # Compaction is a memory
            # optimization. It must not
            # block normal conversation.
            print(
                "[AGENT_MEMORY] "
                "COMPACT_ERROR "
                f"{exc}",
                flush=True,
            )

        with measure("memory_context"):
            snapshot = (
                self.memory
                .prepare_context()
            )

            archive_hits = (
                self.memory
                .search_archive(
                    command,
                    through_turn_id=(
                        snapshot
                        .summarized_through_turn_id
                    ),
                    limit=(
                        self
                        .archive_retrieval_limit
                    ),
                )
            )

        archive_context = ""

        if archive_hits:
            archive_context = "\n\n".join(
                (
                    f"[历史轮次 {hit.turn_id}]\n"
                    f"用户：{hit.user_text}\n"
                    f"LuckRobot："
                    f"{hit.assistant_text}"
                )
                for hit
                in archive_hits
            )

            ids = ",".join(
                str(hit.turn_id)
                for hit
                in archive_hits
            )

            print(
                "[AGENT_MEMORY] RETRIEVE "
                f"hits={len(archive_hits)} "
                f"ids={ids}",
                flush=True,
            )

        payload = {
            "trace_id": trace_id.get(),
            "text": command,
            "local_identity": (
                local_identity
            ),
            "tool_mode": tool_mode,
            "history": (
                snapshot.messages
            ),
            "memory_summary": (
                snapshot
                .memory_summary
            ),
            "archive_context": (
                archive_context
            ),
        }

        if images_jpeg_base64:
            payload[
                "images_jpeg_base64"
            ] = images_jpeg_base64

            print(
                "[VISION] UPLOAD_FRAMES "
                f"count="
                f"{len(images_jpeg_base64)}",
                flush=True,
            )

        with measure("edge_http_chat"):
            data = self._post_chat(payload, cancellation)

        reply = str(
            data.get(
                "reply",
                "",
            )
        ).strip()

        model = str(
            data.get(
                "model",
                "",
            )
        ).strip()

        vision_data = data.get(
            "vision_request"
        )

        if isinstance(
            vision_data,
            dict,
        ):
            mode = str(
                vision_data.get(
                    "mode",
                    "",
                )
            ).strip()

            if mode not in {
                "latest",
                "recent",
            }:
                raise CloudAgentError(
                    "Cloud Agent returned "
                    "invalid vision mode"
                )

            request = VisionRequest(
                mode=mode,
                seconds=float(
                    vision_data.get(
                        "seconds",
                        0.0,
                    )
                ),
                count=int(
                    vision_data.get(
                        "count",
                        1,
                    )
                ),
            )

            print(
                "[VISION] REQUEST "
                f"mode={request.mode} "
                f"seconds={request.seconds:.1f} "
                f"count={request.count}",
                flush=True,
            )

            # A visual acquisition request is
            # an intermediate Agent action,
            # not a completed conversation turn.
            return AgentReply(
                text="",
                model=model,
                vision_request=request,
            )

        tool_data = data.get("tool_request")
        if tool_data is not None:
            if not isinstance(tool_data, dict) or tool_data.get("name") not in LOCAL_SCHEMAS:
                raise CloudAgentError("Unknown local tool request")
            try:
                validate(tool_data.get("arguments"), LOCAL_SCHEMAS[tool_data["name"]])
            except ValueError as exc:
                raise CloudAgentError("Invalid local tool arguments") from exc
            return AgentReply(text="", model=model, tool_request=tool_data)

        music_data = data.get(
            "music_request"
        )

        if isinstance(
            music_data,
            dict,
        ):
            action = str(
                music_data.get(
                    "action",
                    "",
                )
            ).strip()

            allowed_actions = {
                "play_music",
                "pause_music",
                "resume_music",
                "next_music",
                "previous_music",
                "stop_music",
                "select_music",
            }

            if action not in allowed_actions:
                raise CloudAgentError(
                    "Cloud Agent returned "
                    "invalid music action"
                )

            query = str(
                music_data.get(
                    "query",
                    "",
                )
            ).strip()

            request = MusicRequest(
                action=action,
                query=query,
            )

            print(
                "[MUSIC] REQUEST "
                f"action={request.action} "
                f"query={request.query!r}",
                flush=True,
            )

            # Like request_vision, this is
            # an intermediate Edge action.
            # The local runtime executes it
            # before the turn is completed.
            return AgentReply(
                text="",
                model=model,
                vision_request=None,
                music_request=request,
            )

        if not reply:
            raise CloudAgentError(
                "Cloud Agent returned "
                "an empty reply"
            )

        # Only successful exchanges are
        # written to durable memory.
        self.memory.add_turn(
            command,
            reply,
        )

        return AgentReply(
            text=reply,
            model=model,
            vision_request=None,
        )
