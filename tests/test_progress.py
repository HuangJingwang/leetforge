"""Tests for progress.py: table parsing, stats, review, dedup."""

import os
import tempfile
from datetime import date, timedelta

import pytest


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch, tmp_path):
    """Redirect all config paths to a temp directory."""
    monkeypatch.setattr("leetcode_auto.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("leetcode_auto.config.PLAN_DIR", tmp_path)
    monkeypatch.setattr("leetcode_auto.config.PROGRESS_FILE", tmp_path / "progress.md")
    monkeypatch.setattr("leetcode_auto.config.CHECKIN_FILE", tmp_path / "checkin.md")
    monkeypatch.setattr("leetcode_auto.config.PLAN_CONFIG_FILE", tmp_path / "plan_config.json")


SAMPLE_TABLE = """\
# 刷题进度表

| 序号 | 题目 | 难度 | R1 | R2 | R3 | R4 | R5 | 状态 | 最后完成日期 |
| ---: | --- | --- | :---: | :---: | :---: | :---: | :---: | --- | --- |
| 1 | [1. 两数之和](https://leetcode.cn/problems/two-sum/) | 简单 |   |   |   |   |   |   | — |
| 2 | [2. 两数相加](https://leetcode.cn/problems/add-two-numbers/) | 中等 | 2025-03-20 |   |   |   |   | 进行中 | 2025-03-20 |
| 3 | [3. 无重复字符](https://leetcode.cn/problems/longest-substring-without-repeating-characters/) | 中等 | 2025-03-18 | 2025-03-19 | 2025-03-22 | 2025-03-29 | 2025-04-12 | 已完成 | 2025-04-12 |
"""


def _write_table(path, content=SAMPLE_TABLE):
    path.write_text(content, encoding="utf-8")


class TestParseProgressTable:
    def test_basic_parse(self, tmp_path):
        f = tmp_path / "progress.md"
        _write_table(f)
        from leetcode_auto.progress import parse_progress_table
        header, rows = parse_progress_table(f)
        assert len(rows) == 3
        assert rows[0]["title_slug"] == "two-sum"
        assert rows[1]["r1"] == "2025-03-20"
        assert rows[2]["status"] == "已完成"

    def test_slug_extraction(self, tmp_path):
        f = tmp_path / "progress.md"
        _write_table(f)
        from leetcode_auto.progress import parse_progress_table
        _, rows = parse_progress_table(f)
        slugs = [r["title_slug"] for r in rows]
        assert "two-sum" in slugs
        assert "add-two-numbers" in slugs


class TestUpdateProgress:
    def test_fills_first_empty_round(self, tmp_path):
        f = tmp_path / "progress.md"
        _write_table(f)
        from leetcode_auto.progress import parse_progress_table, update_progress
        _, rows = parse_progress_table(f)
        new, review, filled = update_progress(rows, {"two-sum"}, "2025-03-25")
        assert len(new) == 1
        assert rows[0]["r1"] == "2025-03-25"
        assert rows[0]["r2"] == ""  # only R1 filled

    def test_no_duplicate_same_day(self, tmp_path):
        f = tmp_path / "progress.md"
        _write_table(f)
        from leetcode_auto.progress import parse_progress_table, update_progress
        _, rows = parse_progress_table(f)
        # First sync
        update_progress(rows, {"two-sum"}, "2025-03-25")
        assert rows[0]["r1"] == "2025-03-25"
        # Second sync same day — should skip
        update_progress(rows, {"two-sum"}, "2025-03-25")
        assert rows[0]["r2"] == ""  # R2 should NOT be filled

    def test_review_fills_next_round(self, tmp_path):
        f = tmp_path / "progress.md"
        _write_table(f)
        from leetcode_auto.progress import parse_progress_table, update_progress
        _, rows = parse_progress_table(f)
        # add-two-numbers has R1 done, should fill R2
        _, review, _ = update_progress(rows, {"add-two-numbers"}, "2025-03-21")
        assert len(review) == 1
        assert rows[1]["r2"] == "2025-03-21"

    def test_skip_completed(self, tmp_path):
        f = tmp_path / "progress.md"
        _write_table(f)
        from leetcode_auto.progress import parse_progress_table, update_progress
        _, rows = parse_progress_table(f)
        # longest-substring already has all 5 rounds
        new, review, filled = update_progress(
            rows, {"longest-substring-without-repeating-characters"}, "2025-05-01"
        )
        assert len(new) == 0
        assert len(review) == 0


class TestComputeStats:
    def test_stats(self, tmp_path):
        f = tmp_path / "progress.md"
        _write_table(f)
        from leetcode_auto.progress import parse_progress_table, _compute_stats
        _, rows = parse_progress_table(f)
        stats = _compute_stats(rows)
        assert stats["total"] == 3
        assert stats["done_problems"] == 1  # only row 3 is all done
        assert stats["per_round"]["r1"] == 2  # rows 2 and 3

    def test_rate(self, tmp_path):
        f = tmp_path / "progress.md"
        _write_table(f)
        from leetcode_auto.progress import parse_progress_table, _compute_stats
        _, rows = parse_progress_table(f)
        stats = _compute_stats(rows)
        # row2: R1=1, row3: all 5 = 6 rounds done out of 15
        assert stats["done_rounds"] == 6
        assert stats["total_rounds"] == 15


class TestReviewDue:
    def test_review_due(self, tmp_path):
        f = tmp_path / "progress.md"
        _write_table(f)
        from leetcode_auto.progress import parse_progress_table, _get_review_due
        _, rows = parse_progress_table(f)
        # add-two-numbers R1=2025-03-20, R2 interval=1d, due 2025-03-21
        due = _get_review_due(rows, date(2025, 3, 21))
        slugs = [d["title"] for d in due]
        assert any("两数相加" in s for s in slugs)

    def test_no_review_when_not_due(self, tmp_path):
        f = tmp_path / "progress.md"
        _write_table(f)
        from leetcode_auto.progress import parse_progress_table, _get_review_due
        _, rows = parse_progress_table(f)
        # Same day as R1 completion — not due yet
        due = _get_review_due(rows, date(2025, 3, 20))
        assert len(due) == 0


class TestStreak:
    def test_streak(self, tmp_path):
        checkin = tmp_path / "checkin.md"
        today = date.today()
        content = "# 每日打卡\n\n"
        for i in range(3):
            d = today - timedelta(days=i)
            content += f"## {d.strftime('%Y-%m-%d')}（Day {3-i}）\n- 新题完成：题目（1 题）\n- 复习完成：无（0 题）\n- 今日总题数：1\n\n"
        checkin.write_text(content, encoding="utf-8")
        from leetcode_auto.progress import _compute_streak
        streak, total = _compute_streak(checkin)
        assert streak == 3
        assert total == 3
