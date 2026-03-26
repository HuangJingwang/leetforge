"""题目维度数据：笔记、计时、每轮 AI 分析、题解查看状态。

数据结构 (problem_data.json):
{
  "two-sum": {
    "notes": "用哈希表，一遍扫描 O(n)",
    "time_spent": [120, 45, 30],          # 每轮用时（秒）
    "solution_viewed": false,             # 是否看过题解
    "ai_reviews": [
      {"round": "R1", "date": "2025-03-20", "analysis": "..."},
      {"round": "R2", "date": "2025-03-21", "analysis": "..."},
    ]
  },
  ...
}
"""

import json
from .config import DATA_DIR

PROBLEM_DATA_FILE = DATA_DIR / "problem_data.json"


def _load_all() -> dict:
    if not PROBLEM_DATA_FILE.exists():
        return {}
    try:
        return json.loads(PROBLEM_DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return {}


def _save_all(data: dict):
    PROBLEM_DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_entry(entry: dict | None) -> dict:
    entry = dict(entry or {})
    entry.setdefault("notes", "")
    entry.setdefault("time_spent", [])
    entry.setdefault("ai_reviews", [])
    entry.setdefault("solution_viewed", False)
    return entry


def _ensure(data: dict, slug: str) -> dict:
    if slug not in data:
        data[slug] = _normalize_entry({})
    else:
        data[slug] = _normalize_entry(data[slug])
    return data[slug]


# ---------------------------------------------------------------------------
# 笔记
# ---------------------------------------------------------------------------

def get_note(slug: str) -> str:
    return _load_all().get(slug, {}).get("notes", "")


def save_note(slug: str, note: str):
    data = _load_all()
    _ensure(data, slug)["notes"] = note
    _save_all(data)


def is_solution_viewed(slug: str) -> bool:
    return bool(_load_all().get(slug, {}).get("solution_viewed", False))


def set_solution_viewed(slug: str, viewed: bool):
    data = _load_all()
    _ensure(data, slug)["solution_viewed"] = bool(viewed)
    _save_all(data)


# ---------------------------------------------------------------------------
# 计时
# ---------------------------------------------------------------------------

def get_time_spent(slug: str) -> list:
    return _load_all().get(slug, {}).get("time_spent", [])


def add_time_spent(slug: str, seconds: int):
    data = _load_all()
    _ensure(data, slug)["time_spent"].append(seconds)
    _save_all(data)


def get_all_time_stats() -> dict:
    """返回所有题目的计时统计。"""
    data = _load_all()
    stats = {}
    for slug, d in data.items():
        times = d.get("time_spent", [])
        if times:
            stats[slug] = {
                "count": len(times),
                "total": sum(times),
                "avg": sum(times) // len(times),
                "last": times[-1],
            }
    return stats


# ---------------------------------------------------------------------------
# 每轮 AI 分析
# ---------------------------------------------------------------------------

def get_ai_reviews(slug: str) -> list:
    return _load_all().get(slug, {}).get("ai_reviews", [])


def add_ai_review(slug: str, round_key: str, date_str: str, analysis: str):
    data = _load_all()
    _ensure(data, slug)["ai_reviews"].append({
        "round": round_key.upper(),
        "date": date_str,
        "analysis": analysis,
    })
    _save_all(data)


def get_all_problem_data() -> dict:
    """返回全部题目数据，供 Web 前端使用。"""
    return {slug: _normalize_entry(entry) for slug, entry in _load_all().items()}
