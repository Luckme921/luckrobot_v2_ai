from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from edge.agent.memory_store import (
    ConversationMemory,
)


class ConversationMemoryTest(
    unittest.TestCase
):
    def test_raw_archive_is_not_deleted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            memory = ConversationMemory(
                Path(d)
                / "memory.sqlite3",
                recent_turns=100,
                compact_batch_turns=100,
            )

            for i in range(150):
                memory.add_turn(
                    f"user-{i}",
                    f"assistant-{i}",
                )

            # Raw archive keeps everything.
            self.assertEqual(
                memory.turn_count,
                150,
            )

            # Active raw context is bounded.
            snapshot = (
                memory.prepare_context()
            )

            self.assertEqual(
                snapshot.total_turns,
                150,
            )

            self.assertEqual(
                snapshot.recent_turns,
                100,
            )

            self.assertEqual(
                len(snapshot.messages),
                200,
            )

            self.assertEqual(
                snapshot.messages[0][
                    "content"
                ],
                "user-50",
            )

    def test_compaction_bookkeeping(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            db = (
                Path(d)
                / "memory.sqlite3"
            )

            memory = ConversationMemory(
                db,
                recent_turns=100,
                compact_batch_turns=100,
            )

            for i in range(150):
                memory.add_turn(
                    f"user-{i}",
                    f"assistant-{i}",
                )

            batch = (
                memory
                .get_compaction_batch()
            )

            self.assertIsNotNone(
                batch
            )

            assert batch is not None

            self.assertEqual(
                batch.first_turn_id,
                1,
            )

            self.assertEqual(
                batch.last_turn_id,
                100,
            )

            self.assertEqual(
                len(batch.turns),
                100,
            )

            memory.save_compaction(
                batch,
                block_summary=(
                    "第1到100轮摘要"
                ),
                cumulative_summary=(
                    "截至第100轮的"
                    "累计对话记忆"
                ),
            )

            self.assertEqual(
                memory.compaction_count,
                1,
            )

            snapshot = (
                memory.prepare_context()
            )

            self.assertEqual(
                snapshot
                .summarized_through_turn_id,
                100,
            )

            self.assertEqual(
                snapshot
                .pending_compaction_turns,
                50,
            )

            self.assertEqual(
                snapshot.recent_turns,
                50,
            )

            self.assertEqual(
                snapshot.messages[0][
                    "content"
                ],
                "user-100",
            )

            self.assertEqual(
                snapshot.memory_summary,
                (
                    "截至第100轮的"
                    "累计对话记忆"
                ),
            )

            # Re-open DB:
            # raw history + summary both survive.
            memory2 = ConversationMemory(
                db,
                recent_turns=100,
                compact_batch_turns=100,
            )

            self.assertEqual(
                memory2.turn_count,
                150,
            )

            self.assertEqual(
                memory2.compaction_count,
                1,
            )


    def test_archive_retrieval(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            db = (
                Path(d)
                / "memory.sqlite3"
            )

            memory = ConversationMemory(
                db,
                recent_turns=100,
                compact_batch_turns=100,
            )

            memory.add_turn(
                (
                    "纸飞机项目的测试代号"
                    "是Q7X9。"
                ),
                "好的，我记住了。",
            )

            for i in range(2, 101):
                memory.add_turn(
                    f"普通测试对话{i}",
                    f"收到{i}",
                )

            batch = (
                memory
                .get_compaction_batch()
            )

            assert batch is not None

            # Deliberately omit Q7X9
            # from summary.
            memory.save_compaction(
                batch,
                block_summary=(
                    "用户进行了一批测试对话。"
                ),
                cumulative_summary=(
                    "用户正在测试机器人记忆。"
                ),
            )

            snapshot = (
                memory.prepare_context()
            )

            self.assertEqual(
                snapshot.recent_turns,
                0,
            )

            hits = memory.search_archive(
                (
                    "纸飞机项目的"
                    "测试代号是什么"
                ),
                through_turn_id=(
                    snapshot
                    .summarized_through_turn_id
                ),
                limit=6,
            )

            self.assertTrue(hits)

            self.assertEqual(
                hits[0].turn_id,
                1,
            )

            self.assertIn(
                "Q7X9",
                hits[0].user_text,
            )

if __name__ == "__main__":
    unittest.main()
