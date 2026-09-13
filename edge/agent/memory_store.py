from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class MemorySnapshot:
    messages: list[dict[str, str]]
    total_turns: int
    recent_turns: int
    summarized_through_turn_id: int
    pending_compaction_turns: int
    memory_summary: str


@dataclass(frozen=True)
class ArchiveHit:
    turn_id: int
    user_text: str
    assistant_text: str
    score: int


@dataclass(frozen=True)
class CompactionBatch:
    first_turn_id: int
    last_turn_id: int
    turns: list[dict[str, object]]


class ConversationMemory:
    def __init__(
        self,
        db_path: str | Path,
        *,
        recent_turns: int = 100,
        compact_batch_turns: int = 100,
    ) -> None:
        self.db_path = Path(
            db_path
        ).expanduser().resolve()

        self.db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.recent_turns = max(
            1,
            int(recent_turns),
        )

        self.compact_batch_turns = max(
            1,
            int(compact_batch_turns),
        )

        self._init_db()

    def _connect(
        self,
    ) -> sqlite3.Connection:
        return sqlite3.connect(
            self.db_path,
            timeout=5.0,
        )

    def _init_db(
        self,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS
                conversation_turns (
                    id INTEGER PRIMARY KEY
                        AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS
                memory_compactions (
                    id INTEGER PRIMARY KEY
                        AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    first_turn_id INTEGER NOT NULL,
                    last_turn_id INTEGER NOT NULL,
                    block_summary TEXT NOT NULL,
                    cumulative_summary TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_compactions_last_turn
                ON memory_compactions(
                    last_turn_id
                )
                """
            )

            conn.execute(
                "PRAGMA journal_mode=WAL"
            )

    @staticmethod
    def _count_turns(
        conn: sqlite3.Connection,
    ) -> int:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM conversation_turns
            """
        ).fetchone()

        return int(
            row[0]
            if row
            else 0
        )

    @staticmethod
    def _latest_compaction(
        conn: sqlite3.Connection,
    ) -> tuple[int, str]:
        row = conn.execute(
            """
            SELECT
                last_turn_id,
                cumulative_summary
            FROM memory_compactions
            ORDER BY last_turn_id DESC
            LIMIT 1
            """
        ).fetchone()

        if row is None:
            return (
                0,
                "",
            )

        return (
            int(row[0]),
            str(row[1]),
        )

    @staticmethod
    def _rows_to_messages(
        rows: list[tuple],
    ) -> list[dict[str, str]]:
        messages: list[
            dict[str, str]
        ] = []

        for row in rows:
            user_text = str(
                row[-2]
            )

            assistant_text = str(
                row[-1]
            )

            messages.append(
                {
                    "role": "user",
                    "content": user_text,
                }
            )

            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_text,
                }
            )

        return messages

    def prepare_context(
        self,
    ) -> MemorySnapshot:
        with self._connect() as conn:
            (
                summarized_through,
                memory_summary,
            ) = self._latest_compaction(
                conn
            )

            total_turns = (
                self._count_turns(
                    conn
                )
            )

            pending_turns = conn.execute(
                """
                SELECT COUNT(*)
                FROM conversation_turns
                WHERE id > ?
                """,
                (
                    summarized_through,
                ),
            ).fetchone()

            pending_count = int(
                pending_turns[0]
                if pending_turns
                else 0
            )

            # Only unsummarized raw turns
            # belong in the active prompt.
            # Summarized raw turns remain
            # permanently available in the
            # SQLite archive.
            rows = conn.execute(
                """
                SELECT
                    id,
                    user_text,
                    assistant_text
                FROM conversation_turns
                WHERE id > ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (
                    summarized_through,
                    self.recent_turns,
                ),
            ).fetchall()

        # Query newest-first so that if
        # compaction is temporarily
        # unavailable, the Agent still gets
        # the most recent raw conversation.
        # Restore chronological order before
        # building chat messages.
        rows = list(
            reversed(rows)
        )

        return MemorySnapshot(
            messages=(
                self._rows_to_messages(
                    rows
                )
            ),
            total_turns=total_turns,
            recent_turns=len(rows),
            summarized_through_turn_id=(
                summarized_through
            ),
            pending_compaction_turns=(
                pending_count
            ),
            memory_summary=(
                memory_summary
            ),
        )

    def get_compaction_batch(
        self,
    ) -> CompactionBatch | None:
        with self._connect() as conn:
            (
                summarized_through,
                _,
            ) = self._latest_compaction(
                conn
            )

            rows = conn.execute(
                """
                SELECT
                    id,
                    user_text,
                    assistant_text
                FROM conversation_turns
                WHERE id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (
                    summarized_through,
                    self.compact_batch_turns,
                ),
            ).fetchall()

        if (
            len(rows)
            < self.compact_batch_turns
        ):
            return None

        turns: list[
            dict[str, object]
        ] = []

        for (
            turn_id,
            user_text,
            assistant_text,
        ) in rows:
            turns.append(
                {
                    "id": int(
                        turn_id
                    ),
                    "user": str(
                        user_text
                    ),
                    "assistant": str(
                        assistant_text
                    ),
                }
            )

        return CompactionBatch(
            first_turn_id=int(
                rows[0][0]
            ),
            last_turn_id=int(
                rows[-1][0]
            ),
            turns=turns,
        )

    def save_compaction(
        self,
        batch: CompactionBatch,
        *,
        block_summary: str,
        cumulative_summary: str,
    ) -> None:
        block_summary = (
            block_summary.strip()
        )

        cumulative_summary = (
            cumulative_summary.strip()
        )

        if (
            not block_summary
            or not cumulative_summary
        ):
            raise ValueError(
                "Compaction summary "
                "cannot be empty"
            )

        with self._connect() as conn:
            (
                current_through,
                _,
            ) = self._latest_compaction(
                conn
            )

            first_pending = conn.execute(
                """
                SELECT id
                FROM conversation_turns
                WHERE id > ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (
                    current_through,
                ),
            ).fetchone()

            if first_pending is None:
                raise RuntimeError(
                    "No pending turns "
                    "for compaction"
                )

            expected_first = int(
                first_pending[0]
            )

            if (
                batch.first_turn_id
                != expected_first
            ):
                raise RuntimeError(
                    "Compaction batch does "
                    "not start at the first "
                    "pending turn"
                )

            conn.execute(
                """
                INSERT INTO
                memory_compactions(
                    created_at,
                    first_turn_id,
                    last_turn_id,
                    block_summary,
                    cumulative_summary
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    datetime.now()
                    .astimezone()
                    .isoformat(),
                    batch.first_turn_id,
                    batch.last_turn_id,
                    block_summary,
                    cumulative_summary,
                ),
            )

    def add_turn(
        self,
        user_text: str,
        assistant_text: str,
    ) -> None:
        user_text = (
            user_text.strip()
        )

        assistant_text = (
            assistant_text.strip()
        )

        if (
            not user_text
            or not assistant_text
        ):
            return

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO
                conversation_turns(
                    created_at,
                    user_text,
                    assistant_text
                )
                VALUES (?, ?, ?)
                """,
                (
                    datetime.now()
                    .astimezone()
                    .isoformat(),
                    user_text,
                    assistant_text,
                ),
            )

    @staticmethod
    def _search_features(
        query: str,
    ) -> dict[str, int]:
        features: dict[
            str,
            int
        ] = {}

        lowered = query.lower()

        # Numbers / Latin identifiers are
        # especially useful for project names,
        # codes and IDs.
        for token in re.findall(
            r"[a-z0-9_]{2,}",
            lowered,
        ):
            features[token] = max(
                features.get(
                    token,
                    0,
                ),
                20 + len(token),
            )

        # Chinese substring retrieval.
        # Use overlapping n-grams so queries
        # do not need to exactly match the
        # original sentence.
        for span in re.findall(
            r"[\u4e00-\u9fff]{2,}",
            query,
        ):
            max_n = min(
                6,
                len(span),
            )

            min_n = (
                2
                if len(span) <= 4
                else 3
            )

            for n in range(
                min_n,
                max_n + 1,
            ):
                for i in range(
                    0,
                    len(span) - n + 1,
                ):
                    gram = span[
                        i:i + n
                    ]

                    features[gram] = max(
                        features.get(
                            gram,
                            0,
                        ),
                        n * n,
                    )

        return features

    def search_archive(
        self,
        query: str,
        *,
        through_turn_id: int,
        limit: int = 6,
    ) -> list[ArchiveHit]:
        query = query.strip()

        through_turn_id = int(
            through_turn_id
        )

        limit = max(
            1,
            int(limit),
        )

        if (
            not query
            or through_turn_id <= 0
        ):
            return []

        features = (
            self._search_features(
                query
            )
        )

        if not features:
            return []

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    user_text,
                    assistant_text
                FROM conversation_turns
                WHERE id <= ?
                ORDER BY id DESC
                """,
                (
                    through_turn_id,
                ),
            ).fetchall()

        hits: list[
            ArchiveHit
        ] = []

        for (
            turn_id,
            user_text,
            assistant_text,
        ) in rows:
            user_lower = str(
                user_text
            ).lower()

            assistant_lower = str(
                assistant_text
            ).lower()

            combined = (
                user_lower
                + "\n"
                + assistant_lower
            )

            score = 0

            for (
                feature,
                weight,
            ) in features.items():
                if feature in combined:
                    score += weight

                    # Slightly prefer facts
                    # originally said by the
                    # user.
                    if (
                        feature
                        in user_lower
                    ):
                        score += weight

            if score <= 0:
                continue

            hits.append(
                ArchiveHit(
                    turn_id=int(
                        turn_id
                    ),
                    user_text=str(
                        user_text
                    ),
                    assistant_text=str(
                        assistant_text
                    ),
                    score=score,
                )
            )

        hits.sort(
            key=lambda hit: (
                hit.score,
                hit.turn_id,
            ),
            reverse=True,
        )

        return hits[:limit]

    def clear(
        self,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM
                memory_compactions
                """
            )

            conn.execute(
                """
                DELETE FROM
                conversation_turns
                """
            )

    @property
    def turn_count(
        self,
    ) -> int:
        with self._connect() as conn:
            return self._count_turns(
                conn
            )

    @property
    def compaction_count(
        self,
    ) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM memory_compactions
                """
            ).fetchone()

        return int(
            row[0]
            if row
            else 0
        )
