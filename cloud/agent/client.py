from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import AsyncOpenAI


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
            "普通对话自然回答即可。"
            "任何现实世界动作都必须等待"
            "对应工具的实际执行结果，"
            "不能仅通过语言假装已经执行。"
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

    async def chat(
        self,
        text: str,
    ) -> str:
        response = (
            await self.client
            .chat
            .completions
            .create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            self.system_prompt
                        ),
                    },
                    {
                        "role": "user",
                        "content": text,
                    },
                ],
                temperature=(
                    self.temperature
                ),
                max_tokens=(
                    self.max_tokens
                ),
                extra_body={
                    "thinking": {
                        "type": self.thinking,
                    },
                    "reasoning_effort": (
                        self.reasoning_effort
                    ),
                },
            )
        )

        choice = response.choices[0]
        content = (
            choice.message.content
            or ""
        ).strip()

        if not content:
            reasoning = getattr(
                choice.message,
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
