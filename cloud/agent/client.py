from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import AsyncOpenAI

from cloud.agent.tool_router import (
    TOOL_SCHEMAS,
    ToolRouter,
)


class GLMAgent:
    def __init__(
        self,
        config_path: str | Path,
    ) -> None:
        config_path = Path(
            config_path
        ).resolve()

        root = config_path.parents[1]

        load_dotenv(
            dotenv_path=root / ".env",
            override=False,
        )

        with config_path.open(
            "r",
            encoding="utf-8",
        ) as f:
            config = yaml.safe_load(f)

        profile_path = (
            root
            / "configs"
            / "robot_profile.yaml"
        )

        with profile_path.open(
            "r",
            encoding="utf-8",
        ) as f:
            profile = yaml.safe_load(f)

        agent_cfg = config["agent"]

        api_key = os.getenv(
            "ZAI_API_KEY"
        )

        if not api_key:
            raise RuntimeError(
                "ZAI_API_KEY is not configured"
            )

        self.model = agent_cfg["model"]

        self.temperature = float(
            agent_cfg["temperature"]
        )

        self.max_tokens = int(
            agent_cfg["max_tokens"]
        )

        self.thinking = agent_cfg.get(
            "thinking",
            "enabled",
        )

        self.reasoning_effort = agent_cfg.get(
            "reasoning_effort",
            "low",
        )

        profile_text = yaml.safe_dump(
            profile,
            allow_unicode=True,
            sort_keys=False,
        )

        self.system_prompt = (
            "你是实体机器人 LuckRobot "
            "的云端语言与决策代理。\n"
            "下面的角色配置是你的正式产品设定，"
            "必须严格遵守。\n\n"
            f"{profile_text}\n"
            "系统会通过 tools 字段向你提供"
            "当前真正可调用的工具。"
            "当用户请求与某个可用工具匹配时，"
            "必须优先调用工具，"
            "不能只用文字假装执行。"
            "必须根据工具返回的真实结果"
            "向用户说明执行状态。"
        )

        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=agent_cfg[
                "base_url"
            ],
            timeout=float(
                agent_cfg[
                    "timeout_seconds"
                ]
            ),
            max_retries=int(
                agent_cfg[
                    "max_retries"
                ]
            ),
        )

        self.tool_router = ToolRouter()

    def _extra_body(self) -> dict:
        return {
            "thinking": {
                "type": self.thinking,
            },
            "reasoning_effort": (
                self.reasoning_effort
            ),
        }

    async def chat(
        self,
        text: str,
    ) -> str:
        messages: list[dict] = [
            {
                "role": "system",
                "content": self.system_prompt,
            },
            {
                "role": "user",
                "content": text,
            },
        ]

        response = (
            await self.client
            .chat
            .completions
            .create(
                model=self.model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=(
                    self.temperature
                ),
                max_tokens=(
                    self.max_tokens
                ),
                extra_body=(
                    self._extra_body()
                ),
            )
        )

        choice = response.choices[0]
        message = choice.message

        if not message.tool_calls:
            content = (
                message.content
                or ""
            ).strip()

            if not content:
                reasoning = getattr(
                    message,
                    "reasoning_content",
                    "",
                )

                raise RuntimeError(
                    "GLM returned empty content: "
                    f"finish_reason="
                    f"{choice.finish_reason}, "
                    f"reasoning_length="
                    f"{len(reasoning or '')}"
                )

            return content

        assistant_tool_calls = []

        for tool_call in message.tool_calls:
            assistant_tool_calls.append(
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": (
                            tool_call
                            .function
                            .name
                        ),
                        "arguments": (
                            tool_call
                            .function
                            .arguments
                        ),
                    },
                }
            )

        messages.append(
            {
                "role": "assistant",
                "content": (
                    message.content
                    or ""
                ),
                "tool_calls": (
                    assistant_tool_calls
                ),
            }
        )

        tool_results = []

        for tool_call in message.tool_calls:
            try:
                arguments = json.loads(
                    tool_call
                    .function
                    .arguments
                    or "{}"
                )
            except json.JSONDecodeError:
                arguments = {}

            result = (
                await self.tool_router.execute(
                    tool_call.function.name,
                    arguments,
                )
            )

            tool_results.append(result)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": (
                        tool_call.id
                    ),
                    "content": json.dumps(
                        result,
                        ensure_ascii=False,
                    ),
                }
            )

        final_response = (
            await self.client
            .chat
            .completions
            .create(
                model=self.model,
                messages=messages,
                temperature=(
                    self.temperature
                ),
                max_tokens=(
                    self.max_tokens
                ),
                extra_body=(
                    self._extra_body()
                ),
            )
        )

        final_choice = (
            final_response.choices[0]
        )

        content = (
            final_choice
            .message
            .content
            or ""
        ).strip()

        if content:
            return content

        if tool_results:
            return tool_results[-1][
                "message"
            ]

        raise RuntimeError(
            "Tool call completed but "
            "no final response was produced"
        )
