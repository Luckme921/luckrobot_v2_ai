from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import (
    HTTPError,
    URLError,
)
from urllib.request import (
    Request,
    urlopen,
)


class CloudAgentError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentReply:
    text: str
    model: str


class CloudAgentClient:
    def __init__(
        self,
        endpoint: str,
        timeout_seconds: float = 35.0,
    ) -> None:
        self.endpoint = endpoint
        self.timeout_seconds = float(
            timeout_seconds
        )

    def chat(
        self,
        text: str,
    ) -> AgentReply:
        command = text.strip()

        if not command:
            raise CloudAgentError(
                "Agent command is empty"
            )

        payload = json.dumps(
            {
                "text": command,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        request = Request(
            self.endpoint,
            data=payload,
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
                body = response.read()

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
                f"{exc.code}: {detail[:500]}"
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
            data = json.loads(
                body.decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise CloudAgentError(
                "Cloud Agent returned "
                "invalid JSON"
            ) from exc

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

        if not reply:
            raise CloudAgentError(
                "Cloud Agent returned "
                "an empty reply"
            )

        return AgentReply(
            text=reply,
            model=model,
        )
