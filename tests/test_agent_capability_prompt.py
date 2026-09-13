import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from cloud.agent.client import GLMAgent


class AgentCapabilityPromptTest(
    unittest.TestCase
):
    def test_current_tools_override_old_history(
        self,
    ):
        repo_root = (
            Path(__file__)
            .resolve()
            .parents[1]
        )

        config_path = (
            repo_root
            / "configs"
            / "agent.yaml"
        )

        with patch.dict(
            os.environ,
            {
                "ZAI_API_KEY": (
                    "test-key"
                )
            },
        ):
            agent = GLMAgent(
                config_path
            )

        prompt = (
            agent.system_prompt
        )

        self.assertIn(
            "当前 web_search 已正式可用",
            prompt,
        )

        self.assertIn(
            "优先级高于历史对话",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
