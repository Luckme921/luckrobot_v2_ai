from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass


class PulseVolumeError(RuntimeError):
    pass


@dataclass(frozen=True)
class VolumeCommand:
    action: str
    percent: int | None = None


def parse_volume_command(
    text: str,
) -> VolumeCommand | None:
    raw = str(text).strip()
    q = re.sub(
        r"\s+",
        "",
        raw.casefold(),
    )

    if not q:
        return None

    # Short follow-up commands are common after
    # asking about the current volume:
    #
    #   "现在音量是多少"
    #   "调大一点"
    #
    # Match these only as COMPLETE commands.
    # Do not use substring matching here, otherwise
    # phrases such as "字体调大一点" could be
    # mistaken for speaker-volume control.
    if q in {
        "调大一点",
        "调大点",
        "调高一点",
        "调高点",
        "再调大一点",
        "再调大点",
        "再大一点",
        "再大点",
        "大一点",
        "大点",
    }:
        return VolumeCommand(
            action="up"
        )

    if q in {
        "调小一点",
        "调小点",
        "调低一点",
        "调低点",
        "再调小一点",
        "再调小点",
        "再小一点",
        "再小点",
        "小一点",
        "小点",
    }:
        return VolumeCommand(
            action="down"
        )

    # Explicit absolute volume:
    # 音量调到30
    # 音量调到百分之30
    # 声音设为50%
    match = re.search(
        (
            r"(?:音量|声音)"
            r".{0,6}?"
            r"(?:调到|设到|设置为|设为|到)?"
            r"(?:百分之)?"
            r"(\d{1,3})"
            r"%?"
        ),
        q,
    )

    if match:
        return VolumeCommand(
            action="set",
            percent=int(
                match.group(1)
            ),
        )

    if any(
        phrase in q
        for phrase in (
            "最大音量",
            "音量最大",
            "调到最大",
            "声音最大",
            "开到最大",
            "音量开满",
            "声音开满",
        )
    ):
        return VolumeCommand(
            action="max"
        )

    if any(
        phrase in q
        for phrase in (
            "当前音量",
            "现在音量",
            "目前音量",
            "音量多少",
            "声音多大",
            "现在声音多大",
        )
    ):
        return VolumeCommand(
            action="get"
        )

    if any(
        phrase in q
        for phrase in (
            "调大音量",
            "加大音量",
            "加大点音量",
            "我想加大点音量",
            "调高音量",
            "音量调大",
            "音量调大一点",
            "音量调高",
            "音量调高一点",
            "音量大一点",
            "音量大点",
            "声音大一点",
            "声音大点",
            "大声一点",
            "大声点",
            "再大一点",
            "再大点",
        )
    ):
        return VolumeCommand(
            action="up"
        )

    if any(
        phrase in q
        for phrase in (
            "调小音量",
            "调低音量",
            "音量调小",
            "音量调小一点",
            "音量调低",
            "音量调低一点",
            "音量小一点",
            "音量小点",
            "声音小一点",
            "声音小点",
            "小声一点",
            "小声点",
            "再小一点",
            "再小点",
        )
    ):
        return VolumeCommand(
            action="down"
        )

    return None


class PulseVolumeController:
    def __init__(
        self,
        *,
        speaker_match_any: list[str],
        step_percent: int = 10,
        max_percent: int = 100,
    ) -> None:
        self.speaker_match_any = [
            str(item).casefold()
            for item in speaker_match_any
            if str(item).strip()
        ]

        self.step_percent = max(
            1,
            int(step_percent),
        )

        self.max_percent = max(
            1,
            int(max_percent),
        )

    @staticmethod
    def _run(
        args: list[str],
    ) -> str:
        try:
            result = subprocess.run(
                args,
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            raise PulseVolumeError(
                "pactl command failed: "
                + " ".join(args)
            ) from exc

        return result.stdout

    def _sinks(
        self,
    ) -> list[dict]:
        raw = self._run(
            [
                "pactl",
                "-f",
                "json",
                "list",
                "sinks",
            ]
        )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PulseVolumeError(
                "Invalid pactl JSON"
            ) from exc

        if not isinstance(
            data,
            list,
        ):
            raise PulseVolumeError(
                "Unexpected pactl sink data"
            )

        return data

    def _matches_sink(
        self,
        sink: dict,
    ) -> bool:
        properties = (
            sink.get("properties")
            or {}
        )

        haystack = " ".join(
            [
                str(
                    sink.get("name")
                    or ""
                ),
                str(
                    sink.get("description")
                    or ""
                ),
                *[
                    str(value)
                    for value
                    in properties.values()
                ],
            ]
        ).casefold()

        return any(
            token in haystack
            for token
            in self.speaker_match_any
        )

    def _resolve_sink(
        self,
    ) -> dict:
        sinks = self._sinks()

        matches = [
            sink
            for sink in sinks
            if self._matches_sink(
                sink
            )
        ]

        if not matches:
            raise PulseVolumeError(
                "Configured speaker sink "
                "was not found"
            )

        if len(matches) > 1:
            running = [
                sink
                for sink in matches
                if str(
                    sink.get("state")
                    or ""
                ).upper()
                == "RUNNING"
            ]

            if running:
                matches = running

        return matches[0]

    def sink_name(
        self,
    ) -> str:
        sink = self._resolve_sink()

        name = str(
            sink.get("name")
            or ""
        ).strip()

        if not name:
            raise PulseVolumeError(
                "Resolved sink has no name"
            )

        return name

    @staticmethod
    def _percent_from_sink(
        sink: dict,
    ) -> int:
        volume = (
            sink.get("volume")
            or {}
        )

        values: list[int] = []

        if isinstance(
            volume,
            dict,
        ):
            for channel in (
                volume.values()
            ):
                if not isinstance(
                    channel,
                    dict,
                ):
                    continue

                value = str(
                    channel.get(
                        "value_percent"
                    )
                    or ""
                )

                match = re.search(
                    r"(\d+)",
                    value,
                )

                if match:
                    values.append(
                        int(
                            match.group(1)
                        )
                    )

        if not values:
            raise PulseVolumeError(
                "Could not read sink volume"
            )

        return round(
            sum(values)
            / len(values)
        )

    def get_percent(
        self,
    ) -> int:
        return self._percent_from_sink(
            self._resolve_sink()
        )

    def set_percent(
        self,
        percent: int,
    ) -> int:
        target = max(
            0,
            min(
                int(percent),
                self.max_percent,
            ),
        )

        sink = self.sink_name()

        self._run(
            [
                "pactl",
                "set-sink-volume",
                sink,
                f"{target}%",
            ]
        )

        return self.get_percent()

    def increase(
        self,
    ) -> int:
        return self.set_percent(
            self.get_percent()
            + self.step_percent
        )

    def decrease(
        self,
    ) -> int:
        return self.set_percent(
            self.get_percent()
            - self.step_percent
        )

    def execute(
        self,
        command: VolumeCommand,
    ) -> int:
        if command.action == "get":
            return self.get_percent()

        if command.action == "max":
            return self.set_percent(
                self.max_percent
            )

        if command.action == "up":
            return self.increase()

        if command.action == "down":
            return self.decrease()

        if command.action == "set":
            if command.percent is None:
                raise PulseVolumeError(
                    "Volume percentage missing"
                )

            return self.set_percent(
                command.percent
            )

        raise PulseVolumeError(
            "Unsupported volume action: "
            f"{command.action}"
        )


def volume_reply(
    command: VolumeCommand,
    percent: int,
) -> str:
    if command.action == "get":
        return (
            "当前音量是"
            f"百分之{percent}。"
        )

    return (
        "音量已调到"
        f"百分之{percent}。"
    )
