from __future__ import annotations

import re


def normalize_for_speech(
    text: str,
) -> str:
    text = text.strip()

    # Code blocks are not suitable for
    # normal spoken robot replies.
    text = re.sub(
        r"```.*?```",
        "代码内容已省略。",
        text,
        flags=re.DOTALL,
    )

    # Keep inline-code content, but remove
    # Markdown delimiters.
    text = re.sub(
        r"`([^`\n]+)`",
        r"\1",
        text,
    )

    # Long URLs sound terrible in TTS.
    text = re.sub(
        r"https?://\S+",
        "链接",
        text,
    )

    # Kokoro tends to give wave-dash
    # endings an unnatural singing tone.
    text = (
        text
        .replace("～", "。")
        .replace("~", "。")
    )

    # Remove common Markdown decoration.
    text = re.sub(
        r"[*#_]+",
        "",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    text = re.sub(
        r"。{2,}",
        "。",
        text,
    )

    return text.strip()


def _split_long_part(
    text: str,
    max_chars: int,
) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    result: list[str] = []

    while len(text) > max_chars:
        result.append(
            text[:max_chars]
        )

        text = text[max_chars:]

    if text:
        result.append(text)

    return result


def split_for_speech(
    text: str,
    *,
    max_chars: int = 24,
) -> list[str]:
    text = normalize_for_speech(
        text
    )

    if not text:
        return []

    # First split on strong sentence endings.
    sentences = re.findall(
        r".+?[。！？!?；;]|.+$",
        text,
    )

    chunks: list[str] = []

    for sentence in sentences:
        sentence = (
            sentence.strip()
        )

        if not sentence:
            continue

        if len(sentence) <= max_chars:
            chunks.append(sentence)
            continue

        # For an overly long sentence,
        # prefer natural comma/colon boundaries.
        parts = re.findall(
            r".+?[，,:：]|.+$",
            sentence,
        )

        current = ""

        for part in parts:
            part = part.strip()

            if not part:
                continue

            if (
                current
                and
                len(current) + len(part)
                > max_chars
            ):
                chunks.extend(
                    _split_long_part(
                        current,
                        max_chars,
                    )
                )

                current = ""

            if len(part) > max_chars:
                if current:
                    chunks.append(
                        current
                    )
                    current = ""

                chunks.extend(
                    _split_long_part(
                        part,
                        max_chars,
                    )
                )

            else:
                current += part

        if current:
            chunks.append(current)

    return [
        chunk
        for chunk in chunks
        if chunk.strip()
    ]
