from __future__ import annotations

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


class ChatResponse(BaseModel):
    reply: str
    model: str


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
            memory_summary=(
                request.memory_summary
            ),
            archive_context=(
                request.archive_context
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
