from __future__ import annotations

import base64
import json
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
class AgentReply:
    text: str
    model: str
    vision_request: (
        VisionRequest | None
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
    ) -> None:
        self.endpoint = endpoint

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

    def _post_json(
        self,
        endpoint: str,
        payload: dict,
    ) -> dict:
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
                response_body = (
                    response.read()
                )

        except HTTPError as exc:
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
            raise CloudAgentError(
                "Cloud Agent unavailable: "
                f"{exc.reason}"
            ) from exc

        except TimeoutError as exc:
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

            data = self._post_json(
                self.compact_endpoint,
                {
                    "previous_summary": (
                        snapshot
                        .memory_summary
                    ),
                    "turns": (
                        batch.turns
                    ),
                },
            )

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
            self._compact_pending()
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

        data = self._post_json(
            self.endpoint,
            payload,
        )

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
