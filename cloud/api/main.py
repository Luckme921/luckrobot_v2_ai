from __future__ import annotations

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


class ChatResponse(BaseModel):
    reply: str = ""
    model: str
    vision_request: (
        VisionRequestResponse
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


@app.post(
    "/chat",
    response_model=ChatResponse,
)
async def chat(
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

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        ) from exc

    return ChatResponse(
        reply=reply,
        model=agent.model,
    )


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
