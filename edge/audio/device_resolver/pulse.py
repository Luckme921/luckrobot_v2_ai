from __future__ import annotations

import json
import subprocess
from typing import Any


class PulseDeviceNotFound(RuntimeError):
    pass


def _pactl_json(kind: str) -> list[dict[str, Any]]:
    if kind not in {"sources", "sinks"}:
        raise ValueError(f"Unsupported PulseAudio object type: {kind}")

    result = subprocess.run(
        ["pactl", "-f", "json", "list", kind],
        check=True,
        capture_output=True,
        text=True,
    )

    data = json.loads(result.stdout)

    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected pactl JSON for {kind}")

    return data


def _searchable_text(device: dict[str, Any]) -> str:
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                parts.append(str(k))
                walk(v)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif value is not None:
            parts.append(str(value))

    walk(device)
    return " ".join(parts).lower()


def resolve_device(
    kind: str,
    match_any: list[str],
    *,
    exclude_monitor: bool = False,
) -> str:
    devices = _pactl_json(kind)

    candidates: list[dict[str, Any]] = []

    for device in devices:
        name = str(device.get("name", ""))

        if exclude_monitor and name.endswith(".monitor"):
            continue

        searchable = _searchable_text(device)

        if any(token.lower() in searchable for token in match_any):
            candidates.append(device)

    if not candidates:
        available = [
            str(d.get("name", "<unnamed>"))
            for d in devices
            if not (
                exclude_monitor
                and str(d.get("name", "")).endswith(".monitor")
            )
        ]

        raise PulseDeviceNotFound(
            f"No PulseAudio {kind} matched {match_any}. "
            f"Available: {available}"
        )

    # Prefer an actual USB ALSA device name.
    candidates.sort(
        key=lambda d: (
            "usb-" not in str(d.get("name", "")),
            str(d.get("name", "")),
        )
    )

    return str(candidates[0]["name"])


def resolve_microphone(match_any: list[str]) -> str:
    return resolve_device(
        "sources",
        match_any,
        exclude_monitor=True,
    )


def resolve_speaker(match_any: list[str]) -> str:
    return resolve_device(
        "sinks",
        match_any,
    )
