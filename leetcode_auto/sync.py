#!/usr/bin/env python3
"""LeetCode Hot100 每日同步工具

自动获取今日 LeetCode CN 的 AC 记录，筛选 Hot100 题目，
更新刷题进度并检测代码优化空间。

用法:
    leetcode              同步今日刷题记录
    leetcode --web        打开 Web 看板（进度/打卡/复习/优化）
    leetcode --status     炫彩进度面板 + 智能复习提醒
    leetcode --heatmap    GitHub 风格刷题热力图
    leetcode --weakness   分类薄弱点分析
    leetcode --optimize   查看待优化题目列表
    leetcode --report     生成每周报告
    leetcode --badge      生成 SVG 进度徽章
    leetcode --login      打开浏览器重新登录
    leetcode --daemon 30m    每 30 分钟后台同步（关终端不影响）
    leetcode --daemon 1h     每小时后台同步
    leetcode --daemon 23:00  每天 23:00 后台同步
    leetcode --daemon status 查看后台任务状态
    leetcode --daemon stop   卸载后台定时任务
    leetcode --cron 23:00    前台定时同步（终端需保持运行）
"""

import argparse
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta, date
from typing import Optional

import requests

from .config import (
    LEETCODE_API_URL,
    COOKIES_FILE,
    PLAN_DIR,
    PROGRESS_FILE,
    CHECKIN_FILE,
    DASHBOARD_FILE,
    OPTIMIZE_FILE,
    load_credentials,
)
from .init_plan import ensure_plan_files

CST = timezone(timedelta(hours=8))

REVIEW_INTERVALS = {
    "r2": 1,
    "r3": 3,
    "r4": 7,
    "r5": 14,
}

# ---------------------------------------------------------------------------
# 0. 登录状态检测 & 浏览器登录
# ---------------------------------------------------------------------------


class SessionCheckResult:
    """区分"Cookie 过期"和"网络错误"。"""
    def __init__(self, username: Optional[str] = None,
                 expired: bool = False, network_error: bool = False):
        self.username = username
        self.expired = expired
        self.network_error = network_error


def check_session(session: str, csrf: str) -> SessionCheckResult:
    """检查当前 Cookie 是否有效。返回 SessionCheckResult 区分三种情况。"""
    if not session:
        return SessionCheckResult(expired=True)
    query = """
    query globalData {
        userStatus {
            isSignedIn
            userSlug
            username
        }
    }
    """
    headers = {
        "Content-Type": "application/json",
        "Referer": "https://leetcode.cn",
        "Cookie": f"LEETCODE_SESSION={session}; csrftoken={csrf}",
        "x-csrftoken": csrf,
    }
    try:
        resp = requests.post(
            LEETCODE_API_URL, json={"query": query}, headers=headers, timeout=10,
        )
        data = resp.json()
        us = data.get("data", {}).get("userStatus", {})
        if us.get("isSignedIn"):
            slug = us.get("userSlug") or us.get("username")
            return SessionCheckResult(username=slug)
        return SessionCheckResult(expired=True)
    except Exception:
        return SessionCheckResult(network_error=True)


def _ensure_chromium():
    """检查 Chromium 是否已安装，未安装则自动下载。"""
    from pathlib import Path
    cache_dir = Path.home() / "Library" / "Caches" / "ms-playwright"
    if not cache_dir.exists():
        cache_dir = Path.home() / ".cache" / "ms-playwright"
    has_chromium = any(cache_dir.glob("chromium-*/")) if cache_dir.exists() else False
    if not has_chromium:
        print("正在安装 Chromium 浏览器引擎（仅首次需要）...")
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
        print()


def browser_login() -> dict:
    """打开浏览器登录 LeetCode CN，返回凭证字典。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("错误：请先安装 playwright")
        print("  pip install playwright")
        sys.exit(1)

    print("正在启动浏览器...\n", flush=True)

    stealth_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=False, channel="chrome", args=stealth_args)
        except Exception:
            _ensure_chromium()
            browser = p.chromium.launch(headless=False, args=stealth_args)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            window.chrome = { runtime: {} };
        """)
        page = context.new_page()
        page.goto("https://leetcode.cn/accounts/login/")

        print("请在浏览器中完成登录（支持账号密码、微信、GitHub、QQ 等方式）", flush=True)
        print("登录成功后会自动检测，无需手动操作...\n", flush=True)

        import time as _time
        deadline = _time.time() + 300
        session_val = ""
        csrf_val = ""
        while _time.time() < deadline:
            try:
                for c in context.cookies("https://leetcode.cn"):
                    if c["name"] == "LEETCODE_SESSION":
                        session_val = c["value"]
                    elif c["name"] == "csrftoken":
                        csrf_val = c["value"]
            except Exception:
                pass
            if session_val:
                page.wait_for_timeout(1000)
                break
            page.wait_for_timeout(1500)

        if not session_val:
            print("超时（5 分钟内未检测到登录），请重试。", flush=True)
            browser.close()
            sys.exit(1)

        browser.close()

    if not session_val:
        print("未检测到 LEETCODE_SESSION Cookie，登录可能未成功，请重试。", flush=True)
        sys.exit(1)

    result = check_session(session_val, csrf_val)
    username = result.username or "unknown"
    data = {
        "username": username,
        "LEETCODE_SESSION": session_val,
        "csrftoken": csrf_val,
        "saved_at": datetime.now(CST).isoformat(),
    }
    COOKIES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"登录成功！用户：{username}", flush=True)
    print(f"Cookie 已保存到 {COOKIES_FILE}\n", flush=True)
    return {"username": username, "session": session_val, "csrf": csrf_val}


def ensure_credentials(interactive: bool = True) -> dict:
    """加载并验证凭证。interactive=False 时不弹浏览器，凭证失效则返回空。"""
    creds = load_credentials()
    if creds["session"]:
        print("正在检查登录状态...", flush=True)
        result = check_session(creds["session"], creds["csrf"])
        if result.username:
            print(f"已登录：{result.username}\n", flush=True)
            creds["username"] = result.username
            return creds
        if result.network_error:
            print("网络连接失败，跳过登录检查，使用缓存凭证继续。\n", flush=True)
            return creds
        if not interactive:
            print("Cookie 已过期，请手动运行 leetcode --login 重新登录。", flush=True)
            return {}
        print("Cookie 已过期，需要重新登录。\n", flush=True)
    else:
        if not interactive:
            print("未找到登录凭证，请手动运行 leetcode --login 登录。", flush=True)
            return {}
        print("未找到登录凭证，需要登录。\n", flush=True)
    return browser_login()


# ---------------------------------------------------------------------------
# 1. LeetCode API
# ---------------------------------------------------------------------------

SUBMISSION_LIST_QUERY = """
query submissionList($offset: Int!, $limit: Int!, $questionSlug: String!) {
    submissionList(offset: $offset, limit: $limit, questionSlug: $questionSlug) {
        hasNext
        submissions {
            id
            title
            statusDisplay
            timestamp
            url
        }
    }
}
"""


def _make_headers(session: str, csrf: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Referer": "https://leetcode.cn",
        "Cookie": f"LEETCODE_SESSION={session}; csrftoken={csrf}",
        "x-csrftoken": csrf,
    }


def _fetch_submission_list(session: str, csrf: str, limit: int = 80) -> list[dict]:
    """拉取最近提交列表，从 url 字段解析 titleSlug。"""
    headers = _make_headers(session, csrf)
    payload = {
        "query": SUBMISSION_LIST_QUERY,
        "variables": {"offset": 0, "limit": limit, "questionSlug": ""},
    }
    resp = requests.post(LEETCODE_API_URL, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"LeetCode API 返回错误: {data['errors']}")
    subs = data.get("data", {}).get("submissionList", {}).get("submissions") or []
    for s in subs:
        m = re.search(r"/problems/([^/]+)/submissions/", s.get("url", ""))
        s["titleSlug"] = m.group(1) if m else ""
    return subs


def fetch_recent_ac(username: str, session: str, csrf: str, limit: int = 80) -> list[dict]:
    subs = _fetch_submission_list(session, csrf, limit)
    return [s for s in subs if s.get("statusDisplay") == "Accepted"]


def fetch_recent_all(username: str, session: str, csrf: str) -> list[dict]:
    """拉取最近的所有提交（含失败），用于卡点检测。失败时返回空列表。"""
    try:
        return _fetch_submission_list(session, csrf, limit=80)
    except Exception:
        return []


SUBMISSION_DETAIL_QUERY = """
query submissionDetail($submissionId: ID!) {
    submissionDetail(submissionId: $submissionId) {
        id
        code
        runtime
        memory
        runtimePercentile
        memoryPercentile
        lang {
            name
        }
        question {
            titleSlug
            title
            translatedTitle
        }
    }
}
"""


def fetch_submission_detail(session: str, csrf: str, submission_id: str) -> dict:
    """获取单个提交的详细信息（代码、运行时间/内存百分位等）。"""
    headers = _make_headers(session, csrf)
    payload = {
        "query": SUBMISSION_DETAIL_QUERY,
        "variables": {"submissionId": submission_id},
    }
    resp = requests.post(LEETCODE_API_URL, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", {}).get("submissionDetail", {}) or {}


def check_optimization_potential(detail: dict, threshold: float = 50.0) -> Optional[dict]:
    """检查提交是否有优化空间。

    threshold: 百分位阈值，低于此值认为有优化空间（默认 50%）。
    返回优化建议字典，无优化空间返回 None。
    """
    if not detail:
        return None

    runtime_pct = detail.get("runtimePercentile")
    memory_pct = detail.get("memoryPercentile")

    if runtime_pct is None and memory_pct is None:
        return None

    suggestions = []
    runtime_pct = float(runtime_pct) if runtime_pct is not None else None
    memory_pct = float(memory_pct) if memory_pct is not None else None

    if runtime_pct is not None and runtime_pct < threshold:
        suggestions.append(f"运行时间击败 {runtime_pct:.1f}% 用户，建议优化时间复杂度")
    if memory_pct is not None and memory_pct < threshold:
        suggestions.append(f"内存使用击败 {memory_pct:.1f}% 用户，建议优化空间复杂度")

    if not suggestions:
        return None

    question = detail.get("question", {})
    return {
        "title_slug": question.get("titleSlug", ""),
        "title": question.get("translatedTitle") or question.get("title", ""),
        "lang": detail.get("lang", {}).get("name", ""),
        "runtime": detail.get("runtime", ""),
        "memory": detail.get("memory", ""),
        "runtime_pct": runtime_pct,
        "memory_pct": memory_pct,
        "code": detail.get("code", ""),
        "suggestions": suggestions,
    }


def analyze_submissions_for_optimization(
    session: str, csrf: str, today_subs: list[dict], threshold: float = 50.0,
) -> list[dict]:
    """批量分析今日 AC 提交的优化空间。"""
    results = []
    for sub in today_subs:
        sub_id = sub.get("id")
        if not sub_id:
            continue
        try:
            detail = fetch_submission_detail(session, csrf, str(sub_id))
            opt = check_optimization_potential(detail, threshold)
            if opt:
                results.append(opt)
        except Exception:
            continue
    return results


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


def filter_today_ac(submissions: list[dict]) -> list[dict]:
    today_start = datetime.now(CST).replace(hour=0, minute=0, second=0, microsecond=0)
    seen: set[str] = set()
    result: list[dict] = []
    for sub in submissions:
        ts = datetime.fromtimestamp(int(sub["timestamp"]), tz=CST)
        if ts >= today_start and sub["titleSlug"] not in seen:
            seen.add(sub["titleSlug"])
            result.append(sub)
    return result


def detect_struggles(all_subs: list[dict], ac_slugs: set[str]) -> list[str]:
    """检测今日多次提交才 AC 的题目（>=3 次尝试），返回题名列表。"""
    today_start = datetime.now(CST).replace(hour=0, minute=0, second=0, microsecond=0)
    attempt_count: dict[str, int] = {}
    slug_to_title: dict[str, str] = {}
    for sub in all_subs:
        ts = datetime.fromtimestamp(int(sub["timestamp"]), tz=CST)
        if ts < today_start:
            continue
        slug = sub["titleSlug"]
        attempt_count[slug] = attempt_count.get(slug, 0) + 1
        slug_to_title[slug] = sub.get("title", slug)
    return [
        slug_to_title[slug]
        for slug in ac_slugs
        if attempt_count.get(slug, 0) >= 3
    ]


# ---------------------------------------------------------------------------
# 2. 进度表解析 / 写入
# ---------------------------------------------------------------------------

ROUND_KEYS = ("r1", "r2", "r3", "r4", "r5")


def parse_progress_table(filepath) -> tuple[list[str], list[dict]]:
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
        if len(cells) < 10:
            continue
        slug_match = re.search(r"leetcode\.cn/problems/([^/]+)/", cells[1])
        rows.append({
            "seq": cells[0], "title": cells[1], "difficulty": cells[2],
            "r1": cells[3], "r2": cells[4], "r3": cells[5],
            "r4": cells[6], "r5": cells[7],
            "status": cells[8], "last_date": cells[9],
            "title_slug": slug_match.group(1) if slug_match else "",
        })
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
# 3. 核心更新逻辑
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
    """更新进度表，轮次列写入日期而非 ✓。返回 (new, review)。"""
    new_problems: list[str] = []
    review_problems: list[str] = []

    for row in rows:
        if row["title_slug"] not in today_slugs:
            continue
        is_new = not _is_round_done(row["r1"])
        filled = False
        for rk in ROUND_KEYS:
            if not _is_round_done(row[rk]):
                row[rk] = today_str
                filled = True
                break
        if not filled:
            continue
        all_done = all(_is_round_done(row[rk]) for rk in ROUND_KEYS)
        row["status"] = "已完成" if all_done else "进行中"
        row["last_date"] = today_str
        name = _display_title(row["title"])
        (new_problems if is_new else review_problems).append(name)

    return new_problems, review_problems


# ---------------------------------------------------------------------------
# 4. 智能复习（间隔重复）
# ---------------------------------------------------------------------------


def _get_review_due(rows: list[dict], today: date) -> list[dict]:
    """计算今日到期复习的题目，返回 [{title, round, overdue_days}]。"""
    due = []
    round_pairs = [("r1", "r2"), ("r2", "r3"), ("r3", "r4"), ("r4", "r5")]

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
# 5. 数据分析
# ---------------------------------------------------------------------------


def _compute_stats(rows: list[dict]) -> dict:
    total = len(rows)
    total_rounds = total * 5
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


# ---------------------------------------------------------------------------
# 6. 每日打卡
# ---------------------------------------------------------------------------


def _next_day_num(filepath) -> int:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    nums = [int(d) for d in re.findall(r"Day (\d+)", content)]
    return max(nums) + 1 if nums else 1


def update_checkin(
    filepath, today_str: str,
    new_problems: list[str], review_problems: list[str],
    struggles: list[str],
):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if f"## {today_str}" in content:
        print(f"  今日（{today_str}）打卡记录已存在，跳过写入")
        return

    day_num = _next_day_num(filepath)
    new_str = "、".join(new_problems) if new_problems else "无"
    review_str = "、".join(review_problems) if review_problems else "无"
    struggle_str = "、".join(struggles) if struggles else "无"
    total = len(new_problems) + len(review_problems)

    entry = (
        f"\n## {today_str}（Day {day_num}）\n"
        f"- 新题完成：{new_str}（{len(new_problems)} 题）\n"
        f"- 复习完成：{review_str}（{len(review_problems)} 题）\n"
        f"- 今日总题数：{total}\n"
        f"- 卡点题目：{struggle_str}\n"
        f"- 明日计划：\n"
        f"\n---\n\n"
    )

    hint_marker = "> 使用方式"
    if hint_marker in content:
        content = content.replace(hint_marker, entry + hint_marker)
    else:
        content = content.rstrip("\n") + "\n" + entry

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# 7. 进度看板（含智能复习建议）
# ---------------------------------------------------------------------------


def update_dashboard(filepath, rows: list[dict], today_count: int,
                     review_due: list[dict]):
    stats = _compute_stats(rows)

    r1_todo = [
        _display_title(r["title"])
        for r in rows if not _is_round_done(r["r1"])
    ][:5]
    r1_suggestion = "、".join(r1_todo) if r1_todo else "已全部完成 R1"

    review_lines = ""
    if review_due:
        items = review_due[:10]
        review_lines = "\n".join(
            f"  - [{it['round']}] {it['title']}"
            + (f"（逾期 {it['overdue']} 天）" if it['overdue'] > 0 else "（今日到期）")
            for it in items
        )
        if len(review_due) > 10:
            review_lines += f"\n  - ...等共 {len(review_due)} 题"
    else:
        review_lines = "  无到期复习题目"

    content = (
        f"# Hot100 进度看板\n"
        f"\n"
        f"## 总览\n"
        f"- 题目总数：{stats['total']}\n"
        f"- 总轮次数：{stats['total_rounds']}（{stats['total']}×5）\n"
        f"- 已完成轮次：{stats['done_rounds']}\n"
        f"- 今日完成轮次：{today_count}\n"
        f"- 完成率：{stats['rate']:.1f}%\n"
        f"- 已完成题目（5轮全通）：{stats['done_problems']}\n"
        f"\n"
        f"## 今日待办\n"
        f"### 新题（R1 待做）\n"
        f"- {r1_suggestion}\n"
        f"\n"
        f"### 复习（到期提醒）\n"
        f"{review_lines}\n"
        f"\n"
        f"> 复习间隔：R2 +1天 / R3 +3天 / R4 +7天 / R5 +14天\n"
        f"\n"
        f"> 此看板由 leetcode 命令自动更新。\n"
    )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# 8. 桌面通知
# ---------------------------------------------------------------------------


def send_notification(title: str, message: str):
    """发送桌面通知。message 支持多行，自动拆分为 subtitle + body。"""
    system = platform.system()

    # 多行消息拆分：第一行作 subtitle，其余作 body
    lines = message.split("\n")
    subtitle = lines[0] if lines else ""
    body = " | ".join(lines[1:]) if len(lines) > 1 else ""

    def _esc_applescript(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    try:
        if system == "Darwin":
            # 优先用 terminal-notifier（点击"显示"不会打开 Script Editor）
            if shutil.which("terminal-notifier"):
                cmd = ["terminal-notifier",
                       "-title", title, "-message", message,
                       "-group", "leetforge"]
                subprocess.run(cmd, capture_output=True, timeout=5)
            else:
                # osascript: 用 subtitle 在 banner 中展示更多信息
                t = _esc_applescript(title)
                s = _esc_applescript(subtitle)
                b = _esc_applescript(body)
                script = f'display notification "{b}" with title "{t}" subtitle "{s}"'
                if not body:
                    script = f'display notification "{s}" with title "{t}"'
                subprocess.run(["osascript", "-e", script],
                               capture_output=True, timeout=5)
        elif system == "Linux":
            subprocess.run(["notify-send", title, message],
                           capture_output=True, timeout=5)
        elif system == "Windows":
            # 转义单引号，防止 PowerShell 注入
            safe_title = title.replace("'", "''")
            safe_msg = message.replace("\n", "`n").replace("'", "''")
            ps = (
                "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                "$n = New-Object System.Windows.Forms.NotifyIcon; "
                "$n.Icon = [System.Drawing.SystemIcons]::Information; "
                "$n.Visible = $true; "
                f"$n.ShowBalloonTip(5000, '{safe_title}', '{safe_msg}', 'Info')"
            )
            subprocess.run(["powershell", "-Command", ps],
                           capture_output=True, timeout=5)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# main: sync / status / cron / 可视化命令
# ---------------------------------------------------------------------------


def sync(interactive: bool = True):
    today = datetime.now(CST)
    today_str = today.strftime("%Y-%m-%d")
    today_date = today.date()
    print(f"=== LeetCode Hot100 每日同步 ({today_str}) ===\n")

    ensure_plan_files(PLAN_DIR, PROGRESS_FILE, CHECKIN_FILE, DASHBOARD_FILE)
    creds = ensure_credentials(interactive=interactive)
    if not creds:
        send_notification("LeetCode 同步失败", "Cookie 已过期，请运行 leetcode --login")
        return
    username = creds["username"]

    print(f"1. 正在从 LeetCode CN 获取 {username} 的最近 AC 记录...")
    try:
        all_ac = fetch_recent_ac(username, creds["session"], creds["csrf"])
    except Exception as e:
        print(f"   获取失败: {e}")
        sys.exit(1)

    today_subs = filter_today_ac(all_ac)
    print(f"   今日共 {len(today_subs)} 道 AC 提交")

    if not today_subs:
        print("\n今日暂无 AC 提交，无需更新。")
        return

    print("\n2. 正在检测卡点题目...")
    all_subs = fetch_recent_all(username, creds["session"], creds["csrf"])
    ac_slugs = {s["titleSlug"] for s in today_subs}
    struggles = detect_struggles(all_subs, ac_slugs)
    if struggles:
        print(f"   检测到 {len(struggles)} 道卡点题：{', '.join(struggles)}")
    else:
        print("   无卡点题目")

    print("\n3. 正在解析进度表...")
    header_lines, rows = parse_progress_table(PROGRESS_FILE)
    hot100_slugs = {r["title_slug"] for r in rows if r["title_slug"]}

    matched_slugs = {s["titleSlug"] for s in today_subs if s["titleSlug"] in hot100_slugs}
    print(f"   今日 AC 中 {len(matched_slugs)} 道属于 Hot100")

    if not matched_slugs:
        print("\n今日 AC 题目均不在 Hot100 范围内，无需更新。")
        return

    print("\n4. 正在更新进度表...")
    new_problems, review_problems = update_progress(rows, matched_slugs, today_str)
    write_progress_table(PROGRESS_FILE, header_lines, rows)
    print(f"   新题 {len(new_problems)} 道：{', '.join(new_problems) or '无'}")
    print(f"   复习 {len(review_problems)} 道：{', '.join(review_problems) or '无'}")

    print("\n5. 正在更新每日打卡...")
    hot100_struggles = [s for s in struggles if any(
        s == _display_title(r["title"]) for r in rows if r["title_slug"] in matched_slugs
    )]
    update_checkin(CHECKIN_FILE, today_str, new_problems, review_problems, hot100_struggles)
    print("   已写入打卡记录")

    print("\n6. 正在更新进度看板...")
    today_count = len(new_problems) + len(review_problems)
    review_due = _get_review_due(rows, today_date)
    update_dashboard(DASHBOARD_FILE, rows, today_count, review_due)
    stats = _compute_stats(rows)
    print(f"   已完成轮次 {stats['done_rounds']}/{stats['total_rounds']}（{stats['rate']:.1f}%）")
    if review_due:
        print(f"   明日待复习：{len(review_due)} 题")

    print("\n7. 正在分析提交代码优化空间...")
    hot100_today_subs = [s for s in today_subs if s["titleSlug"] in matched_slugs]
    optimizations = analyze_submissions_for_optimization(
        creds["session"], creds["csrf"], hot100_today_subs,
    )
    if optimizations:
        # AI 深度分析
        from .config import get_ai_config
        ai_config = get_ai_config()
        if ai_config["enabled"]:
            print(f"\n8. AI 深度分析（{ai_config['provider']}/{ai_config['model']}）...")
            from .ai_analyzer import batch_analyze
            optimizations = batch_analyze(
                optimizations, creds["session"], creds["csrf"],
            )

        update_optimize_file(OPTIMIZE_FILE, optimizations, today_str)
        opt_titles = [o["title"] for o in optimizations]
        print(f"   检测到 {len(optimizations)} 道题有优化空间：{', '.join(opt_titles)}")
    else:
        print("   所有提交性能表现良好，无需优化")

    msg = f"新题 {len(new_problems)} 道，复习 {len(review_problems)} 道"
    if hot100_struggles:
        msg += f"，卡点 {len(hot100_struggles)} 道"
    if optimizations:
        msg += f"，{len(optimizations)} 道待优化"
    send_notification("LeetCode 同步完成", msg)

    print("\n=== 同步完成 ===")


def status():
    """显示刷题进度 + 智能复习提醒 + 数据分析（Rich 版）。"""
    from .features import rich_status, parse_checkin_data

    ensure_plan_files(PLAN_DIR, PROGRESS_FILE, CHECKIN_FILE, DASHBOARD_FILE)
    _, rows = parse_progress_table(PROGRESS_FILE)
    stats = _compute_stats(rows)
    today_date = date.today()
    review_due = _get_review_due(rows, today_date)
    streak, total_days = _compute_streak(CHECKIN_FILE)
    est = _estimate_completion(stats, total_days)
    checkin_data = parse_checkin_data(CHECKIN_FILE)

    used_rich = rich_status(rows, stats, review_due, streak, total_days, est, checkin_data)

    if not used_rich:
        print("=== LeetCode Hot100 刷题进度 ===\n")
        print(f"题目总数：{stats['total']}")
        print(f"已完成轮次：{stats['done_rounds']}/{stats['total_rounds']}（{stats['rate']:.1f}%）")
        print(f"5 轮全通题目：{stats['done_problems']}/{stats['total']}\n")
        bar_width = 20
        for label, rk in [("R1", "r1"), ("R2", "r2"), ("R3", "r3"),
                           ("R4", "r4"), ("R5", "r5")]:
            done = stats["per_round"][rk]
            filled = int(done / stats["total"] * bar_width) if stats["total"] else 0
            bar = "█" * filled + "░" * (bar_width - filled)
            print(f"  {label} {bar} {done}/{stats['total']}")
        print(f"\n连续打卡：{streak} 天  累计：{total_days} 天  预估完成：{est}")
        if review_due:
            print(f"\n今日到期复习（{len(review_due)} 题）：")
            for it in review_due[:10]:
                flag = f"逾期 {it['overdue']} 天" if it["overdue"] > 0 else "今日到期"
                print(f"  - [{it['round']}] {it['title']}（{flag}）")


def cron_loop(time_str: str):
    try:
        import schedule
    except ImportError:
        print("错误：请安装 schedule 库  pip install schedule")
        sys.exit(1)

    parts = time_str.split(":")
    if len(parts) != 2:
        print("错误：时间格式应为 HH:MM，例如 23:00")
        sys.exit(1)

    schedule.every().day.at(time_str).do(lambda: sync(interactive=False))
    print(f"=== 定时任务已启动，每天 {time_str} 自动同步 ===")
    print("按 Ctrl+C 停止\n")

    def _handle_sigint(_sig, _frame):
        print("\n已停止定时任务。")
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_sigint)
    while True:
        schedule.run_pending()
        time.sleep(30)


def cmd_heatmap():
    from .features import render_heatmap, parse_checkin_data
    ensure_plan_files(PLAN_DIR, PROGRESS_FILE, CHECKIN_FILE, DASHBOARD_FILE)
    checkin_data = parse_checkin_data(CHECKIN_FILE)
    render_heatmap(checkin_data)


def cmd_badge():
    from .features import generate_badge
    ensure_plan_files(PLAN_DIR, PROGRESS_FILE, CHECKIN_FILE, DASHBOARD_FILE)
    _, rows = parse_progress_table(PROGRESS_FILE)
    stats = _compute_stats(rows)
    path = generate_badge(stats)
    print(f"进度徽章已生成：{path}")
    print("可将此 SVG 嵌入 GitHub README 或分享给朋友。")


def cmd_web(port: int):
    from .features import parse_checkin_data
    from .web import serve_web
    ensure_plan_files(PLAN_DIR, PROGRESS_FILE, CHECKIN_FILE, DASHBOARD_FILE)
    _, rows = parse_progress_table(PROGRESS_FILE)
    stats = _compute_stats(rows)
    checkin_data = parse_checkin_data(CHECKIN_FILE)
    streak, total_days = _compute_streak(CHECKIN_FILE)
    today_date = date.today()
    review_due = _get_review_due(rows, today_date)
    est = _estimate_completion(stats, total_days)
    optimizations = _load_optimizations()
    serve_web(rows, stats, checkin_data, streak, total_days,
              review_due, optimizations, est, port)


def cmd_weakness():
    from .features import print_weakness_analysis
    ensure_plan_files(PLAN_DIR, PROGRESS_FILE, CHECKIN_FILE, DASHBOARD_FILE)
    _, rows = parse_progress_table(PROGRESS_FILE)
    print_weakness_analysis(rows)


def remind():
    """计算今日待刷/待复习题目，发送桌面通知。"""
    ensure_plan_files(PLAN_DIR, PROGRESS_FILE, CHECKIN_FILE, DASHBOARD_FILE)
    _, rows = parse_progress_table(PROGRESS_FILE)
    today_date = date.today()

    # 待复习题目
    review_due = _get_review_due(rows, today_date)

    # R1 未做的新题（取前 5 道）
    new_todo = [
        _display_title(r["title"])
        for r in rows if not _is_round_done(r["r1"])
    ][:5]

    # 构建通知内容（每行独立，避免过长截断）
    lines = []
    if review_due:
        review_names = [it["title"] for it in review_due[:3]]
        suffix = f" 等{len(review_due)}题" if len(review_due) > 3 else ""
        lines.append(f"待复习：{'、'.join(review_names)}{suffix}")
    if new_todo:
        new_names = new_todo[:3]
        suffix = f" 等{len(new_todo)}题" if len(new_todo) > 3 else ""
        lines.append(f"新题：{'、'.join(new_names)}{suffix}")

    if lines:
        msg = "\n".join(lines)
    else:
        msg = "今日无待复习题目，继续保持！"

    # 终端输出
    print(f"=== LeetCode 每日提醒 ({today_date}) ===\n")
    if review_due:
        print(f"待复习（{len(review_due)} 题）：")
        for it in review_due[:10]:
            flag = f"逾期 {it['overdue']} 天" if it["overdue"] > 0 else "今日到期"
            print(f"  - [{it['round']}] {it['title']}（{flag}）")
    if new_todo:
        print(f"\n新题推荐：{'、'.join(new_todo)}")
    if not review_due and not new_todo:
        print("今日无待复习题目，继续保持！")

    send_notification("LeetCode 每日提醒", msg)
    print("\n已发送桌面通知。")


def cmd_daemon(arg: str):
    from .daemon import install_daemon, uninstall_daemon, daemon_status
    if arg == "status":
        daemon_status()
    elif arg == "stop":
        uninstall_daemon()
    else:
        install_daemon(arg)


def cmd_remind_daemon(arg: str):
    from .daemon import install_remind_daemon, uninstall_remind_daemon, remind_daemon_status
    if arg == "status":
        remind_daemon_status()
    elif arg == "stop":
        uninstall_remind_daemon()
    else:
        install_remind_daemon()


def cmd_chat():
    """交互式 AI 对话，询问刷题进度和建议。"""
    from .config import get_ai_config
    from .ai_analyzer import build_chat_context, chat

    ai_config = get_ai_config()
    if not ai_config["enabled"]:
        print("错误：未配置 AI。请在 ~/.leetcode_auto/.env 中设置：")
        print("  AI_PROVIDER=openai")
        print("  AI_API_KEY=sk-xxx")
        sys.exit(1)

    print(f"=== LeetForge AI 助手（{ai_config['model']}）===")
    print("输入问题即可对话，输入 q 退出\n")

    system_prompt = build_chat_context()
    history = []

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if not user_input:
            continue
        if user_input.lower() in ("q", "quit", "exit"):
            print("再见！")
            break

        reply = chat(user_input, history, system_prompt)
        if reply:
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": reply})
            print(f"\n助手: {reply}\n")
        else:
            print("\n助手: 抱歉，请求失败，请重试。\n")


def cmd_optimize():
    """查看待优化题目列表。"""
    ensure_plan_files(PLAN_DIR, PROGRESS_FILE, CHECKIN_FILE, DASHBOARD_FILE)
    optimizations = _load_optimizations()
    if not optimizations:
        print("暂无优化建议，运行 leetcode 同步后会自动检测。")
        print("也可使用 leetcode --web 在浏览器中查看。")
        return

    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box

        console = Console()
        table = Table(title="待优化题目", box=box.ROUNDED, show_lines=True)
        table.add_column("日期", width=10)
        table.add_column("题目", style="bold", width=20)
        table.add_column("语言", width=8)
        table.add_column("运行时间", width=12)
        table.add_column("时间排名", width=10)
        table.add_column("内存", width=12)
        table.add_column("内存排名", width=10)

        for o in optimizations:
            rt_pct = o.get("runtime_pct", 0) or 0
            mem_pct = o.get("memory_pct", 0) or 0
            rt_style = "red" if rt_pct < 30 else ("yellow" if rt_pct < 50 else "green")
            mem_style = "red" if mem_pct < 30 else ("yellow" if mem_pct < 50 else "green")
            table.add_row(
                o.get("date", ""),
                o.get("title", ""),
                o.get("lang", ""),
                o.get("runtime", ""),
                f"[{rt_style}]{rt_pct:.1f}%[/{rt_style}]",
                o.get("memory", ""),
                f"[{mem_style}]{mem_pct:.1f}%[/{mem_style}]",
            )

        console.print()
        console.print(table)
        console.print("\n使用 leetcode --web 在浏览器中查看详细代码和建议。")
    except ImportError:
        print("=== 待优化题目 ===\n")
        for o in optimizations:
            print(f"  [{o.get('date', '')}] {o.get('title', '')}（{o.get('lang', '')}）")
            print(f"    运行时间：{o.get('runtime', '')}（击败 {o.get('runtime_pct', 0):.1f}%）")
            print(f"    内存使用：{o.get('memory', '')}（击败 {o.get('memory_pct', 0):.1f}%）")
            print()
        print("使用 leetcode --web 在浏览器中查看详细代码和建议。")


def cmd_report():
    from .features import generate_weekly_report, parse_checkin_data
    ensure_plan_files(PLAN_DIR, PROGRESS_FILE, CHECKIN_FILE, DASHBOARD_FILE)
    _, rows = parse_progress_table(PROGRESS_FILE)
    stats = _compute_stats(rows)
    checkin_data = parse_checkin_data(CHECKIN_FILE)
    path = generate_weekly_report(rows, checkin_data, stats)
    print(f"周报已生成：{path}")


def main():
    parser = argparse.ArgumentParser(
        description="LeetCode Hot100 每日同步工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  leetcode              同步今日刷题记录\n"
            "  leetcode --status     炫彩进度面板\n"
            "  leetcode --heatmap    刷题热力图\n"
            "  leetcode --web        打开交互式 Web 看板\n"
            "  leetcode --weakness   分类薄弱点分析\n"
            "  leetcode --report     生成每周报告\n"
            "  leetcode --badge      生成 SVG 进度徽章\n"
            "  leetcode --optimize   查看待优化题目列表\n"
            "  leetcode --daemon 30m    每 30 分钟后台同步\n"
            "  leetcode --daemon 1h     每小时后台同步\n"
            "  leetcode --daemon 23:00  每天 23:00 后台同步\n"
            "  leetcode --daemon status 查看后台任务状态\n"
            "  leetcode --daemon stop   卸载后台定时任务\n"
            "  leetcode --remind           查看今日待刷/待复习题目\n"
            "  leetcode --remind-daemon    注册每日提醒（10:00/17:00/22:00）\n"
            "  leetcode --remind-daemon status  查看提醒任务状态\n"
            "  leetcode --remind-daemon stop    卸载提醒任务\n"
        ),
    )
    parser.add_argument("--login", action="store_true",
                        help="打开浏览器登录 LeetCode CN")
    parser.add_argument("--status", action="store_true",
                        help="炫彩进度面板 + 智能复习提醒")
    parser.add_argument("--heatmap", action="store_true",
                        help="GitHub 风格刷题热力图")
    parser.add_argument("--badge", action="store_true",
                        help="生成 SVG 进度徽章")
    parser.add_argument("--web", nargs="?", const=8100, type=int,
                        metavar="PORT",
                        help="打开 Web 看板：进度/打卡/复习/优化（默认端口 8100）")
    parser.add_argument("--weakness", action="store_true",
                        help="分类薄弱点分析")
    parser.add_argument("--report", action="store_true",
                        help="生成每周报告")
    parser.add_argument("--optimize", action="store_true",
                        help="查看待优化题目列表")
    parser.add_argument("--chat", action="store_true",
                        help="AI 对话助手，询问进度和刷题建议")
    parser.add_argument("--daemon", nargs="?", const="status",
                        metavar="SCHEDULE",
                        help="后台定时任务：30m/1h/23:00/status/stop")
    parser.add_argument("--remind", action="store_true",
                        help="查看今日待刷/待复习题目并发送通知")
    parser.add_argument("--remind-daemon", nargs="?", const="start",
                        metavar="ACTION",
                        help="每日提醒定时任务（10:00/17:00/22:00）：start/status/stop")
    parser.add_argument("--cron", metavar="HH:MM",
                        help="前台定时同步（终端保持运行）")
    args = parser.parse_args()

    if args.login:
        browser_login()
    elif args.status:
        status()
    elif args.heatmap:
        cmd_heatmap()
    elif args.badge:
        cmd_badge()
    elif args.web is not None:
        cmd_web(args.web)
    elif args.weakness:
        cmd_weakness()
    elif args.report:
        cmd_report()
    elif args.optimize:
        cmd_optimize()
    elif args.chat:
        cmd_chat()
    elif args.remind:
        remind()
    elif args.daemon is not None:
        cmd_daemon(args.daemon)
    elif args.remind_daemon is not None:
        cmd_remind_daemon(args.remind_daemon)
    elif args.cron:
        cron_loop(args.cron)
    else:
        is_background = os.environ.get("LEETFORGE_DAEMON") == "1"
        sync(interactive=not is_background)


if __name__ == "__main__":
    main()
