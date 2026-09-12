from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from cloud.agent.client import GLMAgent


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "agent.yaml"

app = FastAPI(
    title="LuckRobot Cloud Agent",
    version="0.1.0",
)

_agent: GLMAgent | None = None


class ChatRequest(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=4000,
    )


class ChatResponse(BaseModel):
    reply: str
    model: str


def get_agent() -> GLMAgent:
    global _agent

    if _agent is None:
        _agent = GLMAgent(CONFIG)

    return _agent


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "luckrobot-cloud-agent",
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

        reply = await agent.chat(
            request.text
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
