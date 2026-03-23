#!/usr/bin/env python3
"""进度表解析、写入、更新及数据分析函数。"""

import json
import re
from datetime import datetime, timedelta, date
from typing import Optional

from .config import (
    PLAN_DIR,
    get_round_keys,
    get_review_intervals,
)

# ---------------------------------------------------------------------------
# 模块级常量
# ---------------------------------------------------------------------------

ROUND_KEYS = get_round_keys()
REVIEW_INTERVALS = get_review_intervals()

# ---------------------------------------------------------------------------
# 优化建议存储
# ---------------------------------------------------------------------------

_OPTIMIZE_JSON = PLAN_DIR / "optimizations.json"


def _load_optimizations() -> list[dict]:
    """从 JSON 文件加载所有优化建议。"""
    if not _OPTIMIZE_JSON.exists():
        return []
    try:
        return json.loads(_OPTIMIZE_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return []


def _save_optimizations(data: list[dict]):
    """保存优化建议到 JSON 文件。"""
    _OPTIMIZE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def update_optimize_file(filepath, optimizations: list[dict], today_str: str):
    """将优化建议保存到 JSON（供 Web 看板使用）。"""
    if not optimizations:
        return

    existing = _load_optimizations()
    existing_keys = {(o.get("date"), o.get("title_slug")) for o in existing}

    new_entries = []
    for opt in optimizations:
        key = (today_str, opt.get("title_slug", ""))
        if key not in existing_keys:
            opt["date"] = today_str
            new_entries.append(opt)

    if new_entries:
        existing.extend(new_entries)
        _save_optimizations(existing)


# ---------------------------------------------------------------------------
# 进度表解析 / 写入
# ---------------------------------------------------------------------------


def parse_progress_table(filepath) -> tuple[list[str], list[dict]]:
    num_rounds = len(ROUND_KEYS)
    min_cols = 3 + num_rounds + 2  # seq/title/diff + R1..Rn + status/date

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    header_lines: list[str] = []
    rows: list[dict] = []
    table_started = False
    separator_seen = False

    for line in lines:
        stripped = line.strip()
        if not table_started:
            header_lines.append(line)
            if stripped.startswith("| 序号") or stripped.startswith("|序号"):
                table_started = True
            continue
        if not separator_seen:
            header_lines.append(line)
            separator_seen = True
            continue
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.split("|")]
        cells = cells[1:-1]
        if len(cells) < min_cols:
            # 兼容旧表（5轮 = 10列），不足的轮次填空
            while len(cells) < min_cols:
                cells.insert(-2, "")
        slug_match = re.search(r"leetcode\.cn/problems/([^/]+)/", cells[1])
        row = {
            "seq": cells[0], "title": cells[1], "difficulty": cells[2],
            "status": cells[3 + num_rounds],
            "last_date": cells[4 + num_rounds] if len(cells) > 4 + num_rounds else "—",
            "title_slug": slug_match.group(1) if slug_match else "",
        }
        for i, rk in enumerate(ROUND_KEYS):
            row[rk] = cells[3 + i] if 3 + i < len(cells) else ""
        rows.append(row)
    return header_lines, rows


def _row_to_line(row: dict) -> str:
    parts = [
        f" {row['seq']} ", f" {row['title']} ", f" {row['difficulty']} ",
        f" {row['r1'] or ' '} ", f" {row['r2'] or ' '} ",
        f" {row['r3'] or ' '} ", f" {row['r4'] or ' '} ",
        f" {row['r5'] or ' '} ", f" {row['status'] or ' '} ",
        f" {row['last_date']} ",
    ]
    return "|" + "|".join(parts) + "|\n"


def write_progress_table(filepath, header_lines: list[str], rows: list[dict]):
    with open(filepath, "w", encoding="utf-8") as f:
        for line in header_lines:
            f.write(line)
        for row in rows:
            f.write(_row_to_line(row))


# ---------------------------------------------------------------------------
# 核心更新逻辑
# ---------------------------------------------------------------------------


def _display_title(raw_title: str) -> str:
    m = re.search(r"\[(.+?)\]", raw_title)
    return m.group(1) if m else raw_title


def _is_round_done(val: str) -> bool:
    return bool(val) and val not in ("", "—")


def _parse_round_date(val: str) -> Optional[date]:
    """尝试从轮次列解析日期。支持 YYYY-MM-DD 和 MM-DD 格式。✓ 返回 None。"""
    if not val or val in ("—", "✓"):
        return None
    for fmt in ("%Y-%m-%d", "%m-%d"):
        try:
            d = datetime.strptime(val, fmt).date()
            if d.year == 1900:
                d = d.replace(year=date.today().year)
            return d
        except ValueError:
            continue
    return None


def update_progress(rows: list[dict], today_slugs: set[str], today_str: str):
    """更新进度表，轮次列写入日期而非 ✓。返回 (new, review, filled_rounds)。
    filled_rounds: [{slug, round_key, title}] 记录本次填入了哪些轮次。
    """
    new_problems: list[str] = []
    review_problems: list[str] = []
    filled_rounds: list[dict] = []

    for row in rows:
        if row["title_slug"] not in today_slugs:
            continue
        is_new = not _is_round_done(row["r1"])
        filled = False
        for rk in ROUND_KEYS:
            if not _is_round_done(row[rk]):
                row[rk] = today_str
                filled = True
                filled_rounds.append({
                    "slug": row["title_slug"],
                    "round": rk,
                    "title": _display_title(row["title"]),
                })
                break
        if not filled:
            continue
        all_done = all(_is_round_done(row[rk]) for rk in ROUND_KEYS)
        row["status"] = "已完成" if all_done else "进行中"
        row["last_date"] = today_str
        name = _display_title(row["title"])
        (new_problems if is_new else review_problems).append(name)

    return new_problems, review_problems, filled_rounds


# ---------------------------------------------------------------------------
# 智能复习（间隔重复）
# ---------------------------------------------------------------------------


def _get_review_due(rows: list[dict], today: date) -> list[dict]:
    """计算今日到期复习的题目，返回 [{title, round, overdue_days}]。"""
    due = []
    round_pairs = [(ROUND_KEYS[i], ROUND_KEYS[i+1]) for i in range(len(ROUND_KEYS)-1)]

    for row in rows:
        for prev_rk, next_rk in round_pairs:
            if not _is_round_done(row[prev_rk]) or _is_round_done(row[next_rk]):
                continue
            prev_date = _parse_round_date(row[prev_rk])
            if prev_date is None:
                prev_date = _parse_round_date(row["last_date"])
            if prev_date is None:
                continue
            interval = REVIEW_INTERVALS[next_rk]
            due_date = prev_date + timedelta(days=interval)
            if today >= due_date:
                due.append({
                    "title": _display_title(row["title"]),
                    "round": next_rk.upper(),
                    "overdue": (today - due_date).days,
                    "due_date": due_date,
                })
            break
    due.sort(key=lambda x: -x["overdue"])
    return due


# ---------------------------------------------------------------------------
# 数据分析
# ---------------------------------------------------------------------------


def _compute_stats(rows: list[dict]) -> dict:
    total = len(rows)
    num_rounds = len(ROUND_KEYS)
    total_rounds = total * num_rounds
    done_rounds = 0
    done_problems = 0
    per_round = {rk: 0 for rk in ROUND_KEYS}
    for row in rows:
        for rk in ROUND_KEYS:
            if _is_round_done(row[rk]):
                done_rounds += 1
                per_round[rk] += 1
        if all(_is_round_done(row[rk]) for rk in ROUND_KEYS):
            done_problems += 1
    rate = done_rounds / total_rounds * 100 if total_rounds else 0
    return {
        "total": total, "total_rounds": total_rounds,
        "done_rounds": done_rounds, "done_problems": done_problems,
        "rate": rate, "per_round": per_round,
    }


def _compute_streak(filepath) -> tuple[int, int]:
    """从打卡文件计算连续打卡天数和累计天数。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return 0, 0

    dates_str = re.findall(r"## (\d{4}-\d{2}-\d{2})", content)
    if not dates_str:
        return 0, 0

    dates = sorted({datetime.strptime(d, "%Y-%m-%d").date() for d in dates_str}, reverse=True)
    total_days = len(dates)

    streak = 0
    check = date.today()
    for d in dates:
        if d == check or d == check - timedelta(days=1):
            streak += 1
            check = d
        else:
            break
    return streak, total_days


def _estimate_completion(stats: dict, total_days: int) -> str:
    if total_days <= 0 or stats["done_rounds"] <= 0:
        return "数据不足"
    remaining = stats["total_rounds"] - stats["done_rounds"]
    daily_rate = stats["done_rounds"] / total_days
    if daily_rate <= 0:
        return "数据不足"
    days_left = int(remaining / daily_rate)
    target = date.today() + timedelta(days=days_left)
    return f"约 {days_left} 天（预计 {target.strftime('%Y-%m-%d')}）"
