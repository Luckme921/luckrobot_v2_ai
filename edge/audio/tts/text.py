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

    # Normalize whitespace first.
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    # Chinese speech should not inherit
    # arbitrary spaces inserted around
    # Chinese / Latin boundaries by the LLM.
    #
    # Examples:
    #   我是 LuckRobot -> 我是LuckRobot
    #   UP主 luckme 开发 -> UP主luckme开发
    #
    # English-internal spaces such as
    # "OpenAI API" remain untouched.
    cjk = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"

    text = re.sub(
        rf"(?<=[{cjk}]) +",
        "",
        text,
    )

    text = re.sub(
        rf" +(?=[{cjk}])",
        "",
        text,
    )

    # Spaces around Chinese punctuation are
    # also not useful to Kokoro prosody.
    text = re.sub(
        r" *([，。！？；：、]) *",
        r"\1",
        text,
    )

    text = re.sub(
        r"。{2,}",
        "。",
        text,
    )

    return text.strip()


def _sentence_units(
    text: str,
) -> list[str]:
    # Strong punctuation is a genuine
    # spoken sentence boundary.
    return [
        item.strip()
        for item in re.findall(
            r".+?[。！？!?；;]|.+$",
            text,
        )
        if item.strip()
    ]


def _clause_units(
    sentence: str,
) -> list[str]:
    # Comma and colon are optional
    # boundaries for an overlong sentence.
    #
    # Deliberately do NOT split on "、".
    # Enumerations normally sound more
    # natural when Kokoro sees them inside
    # the same synthesis unit.
    return [
        item.strip()
        for item in re.findall(
            r".+?[，,:：]|.+$",
            sentence,
        )
        if item.strip()
    ]


def split_for_speech(
    text: str,
    *,
    max_chars: int = 36,
) -> list[str]:
    """
    Split spoken text at linguistic boundaries.

    max_chars is a SOFT target, not a hard
    character limit.

    Never cut an otherwise indivisible
    Chinese clause merely because it exceeds
    max_chars. A slightly longer synthesis
    unit is preferable to breaking a word or
    semantic phrase in the middle.
    """
    text = normalize_for_speech(
        text
    )

    if not text:
        return []

    max_chars = max(
        8,
        int(max_chars),
    )

    chunks: list[str] = []

    for sentence in _sentence_units(
        text
    ):
        if len(sentence) <= max_chars:
            chunks.append(
                sentence
            )
            continue

        clauses = _clause_units(
            sentence
        )

        current = ""

        for clause in clauses:
            if not current:
                current = clause
                continue

            candidate = (
                current
                + clause
            )

            if (
                len(candidate)
                <= max_chars
            ):
                current = candidate
                continue

            # Flush only at an existing
            # linguistic boundary.
            chunks.append(
                current
            )

            # Important:
            # even if this single clause is
            # longer than max_chars, keep it
            # intact. max_chars is soft.
            current = clause

        if current:
            chunks.append(
                current
            )

    return [
        chunk
        for chunk in chunks
        if chunk.strip()
    ]
