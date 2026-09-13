from __future__ import annotations

import asyncio
import json
import re
import urllib.error
import urllib.request
import uuid


class WebSearchError(RuntimeError):
    pass


class ZhipuWebSearch:
    RECENCY_VALUES = {
        "oneDay",
        "oneWeek",
        "oneMonth",
        "oneYear",
        "noLimit",
    }

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        engine: str = "search_std",
        count: int = 5,
        timeout_seconds: float = 15.0,
        content_size: str = "medium",
        max_content_chars: int = 700,
    ) -> None:
        api_key = api_key.strip()

        if not api_key:
            raise ValueError(
                "Web search API key is empty"
            )

        self.api_key = api_key
        self.endpoint = endpoint.strip()
        self.engine = engine.strip()

        self.count = max(
            1,
            min(
                50,
                int(count),
            ),
        )

        self.timeout_seconds = float(
            timeout_seconds
        )

        self.content_size = str(
            content_size
        ).strip()

        self.max_content_chars = max(
            100,
            int(max_content_chars),
        )

    async def search(
        self,
        query: str,
        *,
        recency: str = "noLimit",
    ) -> dict:
        return await asyncio.to_thread(
            self._search_sync,
            query,
            recency,
        )

    def _search_sync(
        self,
        query: str,
        recency: str,
    ) -> dict:
        query = re.sub(
            r"\s+",
            " ",
            str(query),
        ).strip()

        if not query:
            raise WebSearchError(
                "Search query is empty"
            )

        if len(query) > 70:
            raise WebSearchError(
                "Search query exceeds "
                "70 characters"
            )

        recency = str(
            recency
        ).strip()

        if (
            recency
            not in self.RECENCY_VALUES
        ):
            raise WebSearchError(
                "Unsupported recency: "
                f"{recency}"
            )

        request_id = str(
            uuid.uuid4()
        )

        payload = {
            "search_query": query,
            "search_engine": (
                self.engine
            ),
            "search_intent": False,
            "count": self.count,
            "search_recency_filter": (
                recency
            ),
            "content_size": (
                self.content_size
            ),
            "request_id": request_id,
        }

        body = json.dumps(
            payload,
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Authorization": (
                    f"Bearer {self.api_key}"
                ),
                "Content-Type": (
                    "application/json"
                ),
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=(
                    self.timeout_seconds
                ),
            ) as response:
                raw = response.read()

        except urllib.error.HTTPError as exc:
            raw = exc.read()

            message = raw.decode(
                "utf-8",
                errors="replace",
            )

            raise WebSearchError(
                "Web search HTTP "
                f"{exc.code}: "
                f"{message[:500]}"
            ) from exc

        except urllib.error.URLError as exc:
            raise WebSearchError(
                "Web search connection "
                f"failed: {exc}"
            ) from exc

        except TimeoutError as exc:
            raise WebSearchError(
                "Web search timed out"
            ) from exc

        try:
            data = json.loads(
                raw.decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise WebSearchError(
                "Web search returned "
                "invalid JSON"
            ) from exc

        if "error" in data:
            raise WebSearchError(
                "Web search API error: "
                f"{data['error']}"
            )

        items = data.get(
            "search_result",
            [],
        )

        results = []

        for item in items:
            if not isinstance(
                item,
                dict,
            ):
                continue

            content = re.sub(
                r"\s+",
                " ",
                str(
                    item.get(
                        "content",
                        "",
                    )
                ),
            ).strip()

            if (
                len(content)
                > self.max_content_chars
            ):
                content = (
                    content[
                        :self.max_content_chars
                    ].rstrip()
                    + "…"
                )

            results.append(
                {
                    "title": str(
                        item.get(
                            "title",
                            "",
                        )
                    ).strip(),
                    "content": content,
                    "link": str(
                        item.get(
                            "link",
                            "",
                        )
                    ).strip(),
                    "media": str(
                        item.get(
                            "media",
                            "",
                        )
                    ).strip(),
                    "publish_date": str(
                        item.get(
                            "publish_date",
                            "",
                        )
                    ).strip(),
                }
            )

        return {
            "request_id": str(
                data.get(
                    "request_id",
                    request_id,
                )
            ),
            "query": query,
            "recency": recency,
            "results": results,
        }
