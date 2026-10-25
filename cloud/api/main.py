from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from fastapi.responses import StreamingResponse
from shared.timing import trace_id, progress, measure
from shared.errors import error_info, log_error
from robot_tools.batch import REMOTE_SCHEMAS, result_message
from robot_tools.registry import validate

import base64
import binascii
from pathlib import Path
from typing import Literal

from fastapi import (
    FastAPI,
    HTTPException,
)
from pydantic import (
    BaseModel,
    Field,
)

from cloud.agent.client import (
    GLMAgent,
    LocalToolRequestRequired,
    ToolBatchRequired,
    MusicRequestRequired,
    ConversationEndRequired,
    VisionRequestRequired,
)


ROOT = Path(
    __file__
).resolve().parents[2]

CONFIG = (
    ROOT
    / "configs"
    / "agent.yaml"
)

app = FastAPI(
    title="LuckRobot Cloud Agent",
    version="0.2.0",
)

_agent: GLMAgent | None = None


class ChatMessage(BaseModel):
    role: Literal[
        "user",
        "assistant",
    ]

    content: str = Field(
        min_length=1,
        max_length=4000,
    )


class ChatRequest(BaseModel):
    trace_id: str = Field(default="", max_length=64, pattern=r"^[a-zA-Z0-9_-]*$")

    text: str = Field(
        min_length=1,
        max_length=4000,
    )

    local_identity: Literal[
        "owner",
        "unknown",
        "uncertain",
    ] = "uncertain"

    tool_mode: Literal[
        "auto",
        "none",
    ] = "auto"

    images_jpeg_base64: list[
        str
    ] = Field(
        default_factory=list,
    )

    history: list[
        ChatMessage
    ] = Field(
        default_factory=list,
    )

    memory_summary: str = Field(
        default="",
        max_length=30000,
    )

    archive_context: str = Field(
        default="",
        max_length=30000,
    )
    music_candidates: list[dict] = Field(default_factory=list, max_length=10)


MAX_VISION_IMAGES = 5
MAX_VISION_IMAGE_BYTES = 2_000_000
MAX_VISION_TOTAL_BYTES = 5_000_000
MAX_VISION_BASE64_CHARS = 3_000_000


def _decode_vision_images(
    encoded_images: list[str],
) -> list[str]:
    if len(encoded_images) > MAX_VISION_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Too many vision images; "
                f"maximum is "
                f"{MAX_VISION_IMAGES}"
            ),
        )

    data_urls: list[str] = []
    total_bytes = 0

    for index, encoded in enumerate(
        encoded_images
    ):
        encoded = str(
            encoded
        ).strip()

        if not encoded:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Vision image "
                    f"{index} is empty"
                ),
            )

        if (
            len(encoded)
            > MAX_VISION_BASE64_CHARS
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Vision image "
                    f"{index} base64 payload "
                    "is too large"
                ),
            )

        try:
            jpeg = base64.b64decode(
                encoded,
                validate=True,
            )
        except (
            binascii.Error,
            ValueError,
        ) as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Vision image "
                    f"{index} has invalid "
                    "base64 data"
                ),
            ) from exc

        if (
            len(jpeg)
            > MAX_VISION_IMAGE_BYTES
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Vision image "
                    f"{index} exceeds "
                    "the size limit"
                ),
            )

        if (
            len(jpeg) < 4
            or jpeg[:2] != b"\xff\xd8"
            or jpeg[-2:] != b"\xff\xd9"
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Vision image "
                    f"{index} is not "
                    "a complete JPEG"
                ),
            )

        total_bytes += len(
            jpeg
        )

        if (
            total_bytes
            > MAX_VISION_TOTAL_BYTES
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Total vision image "
                    "payload exceeds "
                    "the size limit"
                ),
            )

        data_urls.append(
            "data:image/jpeg;base64,"
            + encoded
        )

    return data_urls


class VisionRequestResponse(
    BaseModel
):
    mode: Literal[
        "latest",
        "recent",
    ]
    seconds: float
    count: int


class MusicRequestResponse(
    BaseModel
):
    action: Literal[
        "play_music",
        "recommend_music",
        "pause_music",
        "resume_music",
        "next_music",
        "previous_music",
        "stop_music",
        "select_music",
    ]
    query: str = ""


class LocalToolResponse(BaseModel):
    name: Literal["volume_control", "music_search", "music_select", "music_control", "fan_light_control"]
    arguments: dict

class BatchToolResponse(BaseModel):
    name: Literal["volume_control", "music_search", "music_select", "music_control", "fan_light_control", "get_weather", "web_search", "navigate_to"]
    arguments: dict


class ChatResponse(BaseModel):
    tool_requests: list[BatchToolResponse] = Field(default_factory=list, max_length=4)
    tool_request: LocalToolResponse | None = None

    reply: str = ""
    model: str
    end_conversation: bool = False
    vision_request: (
        VisionRequestResponse
        | None
    ) = None
    music_request: (
        MusicRequestResponse
        | None
    ) = None


def get_agent() -> GLMAgent:
    global _agent

    if _agent is None:
        _agent = GLMAgent(
            CONFIG
        )

    return _agent


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": (
            "luckrobot-cloud-agent"
        ),
    }


class RemoteToolRequest(BaseModel):
    name: Literal["get_weather", "web_search", "navigate_to"]
    arguments: dict
    trace_id: str = Field(default="", max_length=64, pattern=r"^[a-zA-Z0-9_-]*$")


@app.post("/tools/execute")
async def execute_remote_tool(request: RemoteToolRequest):
    try:
        validate(request.arguments, REMOTE_SCHEMAS[request.name])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid tool arguments") from exc
    token = trace_id.set(request.trace_id or uuid.uuid4().hex)
    try:
        agent = get_agent()
        with measure("tool_" + request.name):
            result = await agent.tool_router.execute(request.name, request.arguments)
        result["message"] = result_message(result)
        return result
    except Exception as exc:
        log_error(exc, "remote_tool")
        return {"ok": False, "tool": request.name, "status": "error",
                "executed": False, "message": "这个查询未完成，请稍后再试。"}
    finally:
        trace_id.reset(token)


async def _chat(
    request: ChatRequest,
) -> ChatResponse:
    image_data_urls = (
        _decode_vision_images(
            request.images_jpeg_base64
        )
    )

    try:
        agent = get_agent()

        # Defense in depth:
        # Edge currently keeps up to one hundred turns,
        # and API accepts at most the newest
        # two hundred messages for one request.
        history = [
            {
                "role": item.role,
                "content": item.content,
            }
            for item
            in request.history[-200:]
        ]

        reply = await agent.chat(
            request.text,
            history=history,
            local_identity=(
                request.local_identity
            ),
            tool_mode=(
                request.tool_mode
            ),
            memory_summary=(
                request.memory_summary
            ),
            archive_context=(
                request.archive_context
            ),
            music_candidates=request.music_candidates,
            image_data_urls=(
                image_data_urls
            ),
        )

    except VisionRequestRequired as exc:
        vision = exc.request

        return ChatResponse(
            reply="",
            model=agent.model,
            vision_request=(
                VisionRequestResponse(
                    mode=vision.mode,
                    seconds=(
                        vision.seconds
                    ),
                    count=vision.count,
                )
            ),
        )

    except ToolBatchRequired as exc:
        return ChatResponse(reply="", model=agent.model, end_conversation=exc.end_conversation,
                            tool_requests=[BatchToolResponse(**item) for item in exc.requests])

    except LocalToolRequestRequired as exc:
        return ChatResponse(reply="", model=agent.model,
                            tool_request=LocalToolResponse(name=exc.name, arguments=exc.arguments))

    except MusicRequestRequired as exc:
        music = exc.request

        return ChatResponse(
            reply="",
            model=agent.model,
            music_request=(
                MusicRequestResponse(
                    action=music.action,
                    query=music.query,
                )
            ),
        )

    except ConversationEndRequired as exc:
        return ChatResponse(reply=exc.reply, model=agent.model, end_conversation=True)

    except Exception as exc:
        info = log_error(exc, "chat")
        raise HTTPException(status_code=502, detail=info) from exc

    return ChatResponse(
        reply=reply,
        model=agent.model,
    )



async def _scoped_chat(request, callback=None):
    token = trace_id.set(request.trace_id or uuid.uuid4().hex)
    progress_token = progress.set(callback)
    try:
        with measure("cloud_total"):
            return await _chat(request)
    finally:
        progress.reset(progress_token)
        trace_id.reset(token)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return await _scoped_chat(request)


async def chat_events(request):
    queue = asyncio.Queue()

    async def run():
        try:
            reply = await _scoped_chat(request, queue.put_nowait)
            await queue.put({"type": "result", "data": reply.model_dump()})
        except Exception as exc:
            info = error_info(exc)
            # The wrapper may be HTTPException; retain its original cause.
            print("[AGENT_ERROR] " + json.dumps(
                {"trace_id": request.trace_id, "stage": "chat_events", **info}), flush=True)
            await queue.put({"type": "error", "error": info["type"],
                             "reason": info["reason"]})
        finally:
            await queue.put(None)

    task = asyncio.create_task(run())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False) + "\n"
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@app.post("/chat/events")
async def stream_chat(request: ChatRequest):
    return StreamingResponse(chat_events(request),
                             media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


class CompactTurn(BaseModel):
    id: int
    user: str = Field(
        min_length=1,
        max_length=4000,
    )
    assistant: str = Field(
        min_length=1,
        max_length=8000,
    )


class CompactRequest(BaseModel):
    previous_summary: str = Field(
        default="",
        max_length=30000,
    )
    turns: list[CompactTurn] = Field(
        min_length=1,
        max_length=100,
    )


class CompactResponse(BaseModel):
    block_summary: str
    cumulative_summary: str
    model: str


@app.post(
    "/compact",
    response_model=CompactResponse,
)
async def compact(
    request: CompactRequest,
) -> CompactResponse:
    try:
        agent = get_agent()

        turns = [
            {
                "id": item.id,
                "user": item.user,
                "assistant": (
                    item.assistant
                ),
            }
            for item in request.turns
        ]

        (
            block_summary,
            cumulative_summary,
        ) = await agent.compact_memory(
            previous_summary=(
                request.previous_summary
            ),
            turns=turns,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        ) from exc

    return CompactResponse(
        block_summary=block_summary,
        cumulative_summary=(
            cumulative_summary
        ),
        model=agent.model,
    )
