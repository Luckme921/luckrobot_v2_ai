from __future__ import annotations

import time
import re
from dataclasses import dataclass


_TRIM_CHARS = (
    " \t\r\n"
    ",，"
    ".。"
    "!！"
    "?？"
    ":："
    ";；"
    "、"
)


@dataclass(frozen=True)
class GateDecision:
    action: str
    command: str | None
    wake_detected: bool
    state: str
    mode: str
    reason: str

    @property
    def command_for_model(self) -> str | None:
        if self.command is None:
            return None
        if self.wake_detected:
            return f"Lucky，{self.command}"
        return self.command


class InteractionGate:
    SLEEPING = "sleeping"
    AWAKE_WAIT_COMMAND = (
        "awake_wait_command"
    )
    ACTIVE = "active"

    COMMAND_MODE = "command"
    CHAT_MODE = "chat"

    def __init__(
        self,
        *,
        wake_command_timeout_seconds: float,
        normal_timeout_seconds: float,
        chat_timeout_seconds: float,
        transcript_aliases: list[str],
        transcript_exact_aliases: list[str],
        chat_mode_triggers: list[str],
        sleep_phrases: list[str],
        emergency_stop_phrases: list[str],
        post_kws_transcript_aliases: list[str] | None = None,
        include_pre_wake_speech: bool = False,
        enabled: bool = True,
    ) -> None:
        self.enabled = bool(
            enabled
        )
        self.include_pre_wake_speech = bool(include_pre_wake_speech)

        self.wake_command_timeout_seconds = (
            float(
                wake_command_timeout_seconds
            )
        )

        self.normal_timeout_seconds = float(
            normal_timeout_seconds
        )

        self.chat_timeout_seconds = float(
            chat_timeout_seconds
        )

        self.transcript_aliases = [
            item.strip()
            for item in transcript_aliases
            if item.strip()
        ]

        self.transcript_exact_aliases = [
            item.strip()
            for item
            in transcript_exact_aliases
            if item.strip()
        ]

        self.post_kws_transcript_aliases = [
            item.strip()
            for item in (post_kws_transcript_aliases or [])
            if item.strip()
        ]

        self.chat_mode_triggers = [
            item.strip()
            for item in chat_mode_triggers
            if item.strip()
        ]

        self.sleep_phrases = [
            item.strip()
            for item in sleep_phrases
            if item.strip()
        ]

        self.emergency_stop_phrases = [
            item.strip()
            for item
            in emergency_stop_phrases
            if item.strip()
        ]

        self.reset()

    @staticmethod
    def _clean(
        text: str,
    ) -> str:
        return text.strip(
            _TRIM_CHARS
        )

    def reset(self) -> None:
        self.state = self.SLEEPING
        self.mode = self.COMMAND_MODE
        self.deadline = 0.0

    def on_wake(
        self,
        now: float | None = None,
    ) -> None:
        if now is None:
            now = time.monotonic()

        self.state = (
            self.AWAKE_WAIT_COMMAND
        )

        self.mode = self.COMMAND_MODE

        self.deadline = (
            now
            + self.wake_command_timeout_seconds
        )

    def expire_if_needed(
        self,
        now: float | None = None,
    ) -> bool:
        if not self.enabled:
            return False

        if now is None:
            now = time.monotonic()

        if (
            self.state != self.SLEEPING
            and self.deadline > 0.0
            and now > self.deadline
        ):
            self.reset()
            return True

        return False

    def _is_chat_command(
        self,
        text: str,
    ) -> bool:
        return any(
            trigger in text
            for trigger
            in self.chat_mode_triggers
        )

    def _is_sleep_request(
        self,
        text: str,
    ) -> bool:
        # Match a complete command, not a quoted phrase or a negated request.
        compact = re.sub(r"[\s，。！？,.!?、；;：:]+", "", text.casefold())
        phrases = set(self.sleep_phrases) | {
            "结束对话", "结束聊天", "停止对话", "停止聊天",
            "退出对话", "退出聊天", "关闭对话", "取消对话",
            "不用回答了", "不要再回答了",
        }
        for phrase in phrases:
            pattern = (r"(?:(?:请|麻烦你|帮我|现在|我们|先))*"
                       + re.escape(phrase.casefold())
                       + r"(?:吧|了|谢谢|好吗|可以吗)*")
            if re.fullmatch(pattern, compact):
                return True
        return False

    def _is_emergency_stop(
        self,
        text: str,
    ) -> bool:
        cleaned = self._clean(text)

        return any(
            cleaned.startswith(phrase)
            for phrase
            in self.emergency_stop_phrases
        )

    def _active_timeout(
        self,
    ) -> float:
        if self.mode == self.CHAT_MODE:
            return (
                self.chat_timeout_seconds
            )

        return (
            self.normal_timeout_seconds
        )

    def _activate(
        self,
        text: str,
        now: float,
    ) -> None:
        if self._is_chat_command(
            text
        ):
            self.mode = self.CHAT_MODE

        self.state = self.ACTIVE

        self.deadline = (
            now
            + self._active_timeout()
        )

    def _strip_wake_echo(
        self,
        text: str,
        *,
        after_kws: bool = False,
    ) -> str:
        """
        Clean SenseVoice's transcription of the
        wake word after KWS has already detected it.

        Prefix aliases may be removed from:
          lucky,你在吗
          阿K,你在吗
          拉ucky带我去厨房

        Exact-only aliases are removed only when
        they are the whole utterance. This prevents
        an ASR error such as "拉" from damaging a
        real command such as "拉开窗帘".
        """
        cleaned = self._clean(
            text
        )

        folded = cleaned.casefold()

        for alias in (
            self.transcript_exact_aliases
        ):
            if (
                folded
                == alias.casefold()
            ):
                return ""

        aliases = sorted(
            self.transcript_aliases
            + (self.post_kws_transcript_aliases if after_kws else []),
            key=len,
            reverse=True,
        )

        if after_kws and not self.include_pre_wake_speech:
            # The VAD segment may start before KWS fires. Only an actual ASR
            # wake alias provides a safe boundary within that segment.
            positions = [(folded.find(alias.casefold()), alias) for alias in aliases]
            positions = [(position, alias) for position, alias in positions if position > 0]
            if positions:
                position, alias = min(positions, key=lambda item: item[0])
                return self._clean(cleaned[position + len(alias):])

        for alias in aliases:
            alias_folded = (
                alias.casefold()
            )

            if not folded.startswith(
                alias_folded
            ):
                continue

            remainder = cleaned[
                len(alias):
            ]

            if remainder:
                first = remainder[0]

                # Do not interpret an ordinary
                # longer English word as a wake echo.
                if (
                    first.isascii()
                    and (
                        first.isalnum()
                        or first == "_"
                    )
                ):
                    continue

            return self._clean(
                remainder
            )

        return cleaned

    def on_robot_reply_finished(
        self,
        now: float | None = None,
    ) -> None:
        if now is None:
            now = time.monotonic()

        if self.state == self.ACTIVE:
            self.deadline = (
                now
                + self._active_timeout()
            )

    def process(
        self,
        text: str,
        now: float | None = None,
    ) -> GateDecision:
        if now is None:
            now = time.monotonic()

        text = self._clean(
            text
        )

        if not text:
            return GateDecision(
                action="ignore",
                command=None,
                wake_detected=False,
                state=self.state,
                mode=self.mode,
                reason="empty",
            )

        if (self.enabled and self.state != self.SLEEPING
                and self._is_sleep_request(self._strip_wake_echo(text))):
            self.reset()
            return GateDecision(
                action="sleep", command=None, wake_detected=False,
                state=self.state, mode=self.mode, reason="user_sleep_request")

        if self._is_emergency_stop(
            text
        ):
            return GateDecision(
                action="emergency_stop",
                command="stop_navigation",
                wake_detected=False,
                state=self.state,
                mode=self.mode,
                reason="local_safety_phrase",
            )

        if not self.enabled:
            self._activate(
                text,
                now,
            )

            return GateDecision(
                action="command",
                command=text,
                wake_detected=False,
                state=self.state,
                mode=self.mode,
                reason="gate_disabled",
            )

        self.expire_if_needed(
            now
        )

        if self.state == self.SLEEPING:
            return GateDecision(
                action="ignore",
                command=None,
                wake_detected=False,
                state=self.state,
                mode=self.mode,
                reason="sleeping",
            )

        if (
            self.state
            == self.AWAKE_WAIT_COMMAND
        ):
            command = self._clean(
                self._strip_wake_echo(
                    text,
                    after_kws=True,
                )
            )

            wake_echo_detected = command != text

            # The VAD/ASR segment contained only
            # the wake word. Keep waiting.
            greeting = re.sub(r"[\s，。！？,.!?]+", "", command).casefold()
            if not command or greeting in {"你好", "你好呀", "你好啊", "嗨", "hello", "hi", "在吗", "你在吗"}:
                return GateDecision(
                    action="awake",
                    command=None,
                    wake_detected=wake_echo_detected,
                    state=self.state,
                    mode=self.mode,
                    reason="wake_greeting" if command else "wake_echo_only",
                )

            if len(re.sub(r"[\s\W_]+", "", command, flags=re.UNICODE)) < 3:
                return GateDecision(
                    action="ignore", command=None, wake_detected=wake_echo_detected,
                    state=self.state, mode=self.mode, reason="short_after_wake",
                )

            self._activate(
                command,
                now,
            )

            return GateDecision(
                action="command",
                command=command,
                wake_detected=wake_echo_detected,
                state=self.state,
                mode=self.mode,
                reason="command_after_kws",
            )

        if self.state == self.ACTIVE:
            command = self._clean(
                self._strip_wake_echo(
                    text
                )
            )

            # It is common to say the wake word
            # again during an active conversation.
            # Treat a wake-only utterance as noise
            # instead of sending it to the Agent.
            if not command:
                self.deadline = (
                    now
                    + self._active_timeout()
                )

                return GateDecision(
                    action="awake",
                    command=None,
                    wake_detected=False,
                    state=self.state,
                    mode=self.mode,
                    reason="active_wake_echo_only",
                )

            if len(re.sub(r"[\s\W_]+", "", command, flags=re.UNICODE)) < 2:
                return GateDecision(
                    action="ignore", command=None, wake_detected=False,
                    state=self.state, mode=self.mode, reason="short_active_fragment",
                )

            self._activate(
                command,
                now,
            )

            return GateDecision(
                action="command",
                command=command,
                wake_detected=False,
                state=self.state,
                mode=self.mode,
                reason="active_followup",
            )

        return GateDecision(
            action="ignore",
            command=None,
            wake_detected=False,
            state=self.state,
            mode=self.mode,
            reason="unknown_state",
        )
