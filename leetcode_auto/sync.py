#!/usr/bin/env python3
"""LeetCode Hot100 每日同步工具

自动获取今日 LeetCode CN 的 AC 记录，筛选 Hot100 题目，
更新桌面刷题计划中的进度表、每日打卡和进度看板。

用法:
    leetcode              同步今日刷题记录
    leetcode --status     炫彩进度面板 + 智能复习提醒
    leetcode --heatmap    GitHub 风格刷题热力图
    leetcode --web        交互式 Web 看板
    leetcode --weakness   分类薄弱点分析
    leetcode --report     生成每周报告
    leetcode --badge      生成 SVG 进度徽章
    leetcode --login      打开浏览器重新登录
    leetcode --cron 23:00 每天定时自动同步
"""

import argparse
import json
import platform
import re
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


def check_session(session: str, csrf: str) -> Optional[str]:
    """检查当前 Cookie 是否有效，有效返回 userSlug，无效返回 None。"""
    if not session:
        return None
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
            return us.get("userSlug") or us.get("username")
    except Exception:
        pass
    return None


def _ensure_chromium():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.executable_path
    except Exception:
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

    _ensure_chromium()
    print("正在启动浏览器...\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://leetcode.cn/accounts/login/")

        print("请在浏览器中完成登录（支持账号密码、微信、GitHub 等方式）")
        print("登录成功后会自动检测，无需手动操作...\n")

        try:
            page.wait_for_url(
                lambda url: "leetcode.cn" in url and "/accounts/login" not in url,
                timeout=300_000,
            )
        except Exception:
            print("超时（5 分钟内未检测到登录），请重试。")
            browser.close()
            sys.exit(1)

        page.wait_for_timeout(2000)
        cookies = context.cookies("https://leetcode.cn")
        session_val = ""
        csrf_val = ""
        for c in cookies:
            if c["name"] == "LEETCODE_SESSION":
                session_val = c["value"]
            elif c["name"] == "csrftoken":
                csrf_val = c["value"]
        browser.close()

    if not session_val:
        print("未检测到 LEETCODE_SESSION Cookie，登录可能未成功，请重试。")
        sys.exit(1)

    username = check_session(session_val, csrf_val) or "unknown"
    data = {
        "username": username,
        "LEETCODE_SESSION": session_val,
        "csrftoken": csrf_val,
        "saved_at": datetime.now(CST).isoformat(),
    }
    COOKIES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"登录成功！用户：{username}")
    print(f"Cookie 已保存到 {COOKIES_FILE}\n")
    return {"username": username, "session": session_val, "csrf": csrf_val}


def ensure_credentials() -> dict:
    creds = load_credentials()
    if creds["session"]:
        print("正在检查登录状态...")
        username = check_session(creds["session"], creds["csrf"])
        if username:
            print(f"已登录：{username}\n")
            creds["username"] = username
            return creds
        print("Cookie 已过期，需要重新登录。\n")
    else:
        print("未找到登录凭证，需要登录。\n")
    return browser_login()


# ---------------------------------------------------------------------------
# 1. LeetCode API
# ---------------------------------------------------------------------------

RECENT_AC_QUERY = """
query recentAcSubmissions($userSlug: String!, $limit: Int) {
    recentACSubmissions(userSlug: $userSlug, limit: $limit) {
        id
        title
        titleSlug
        timestamp
    }
}
"""

RECENT_ALL_QUERY = """
query recentSubmissions($userSlug: String!) {
    recentSubmissions(userSlug: $userSlug) {
        title
        titleSlug
        timestamp
        statusDisplay
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


def fetch_recent_ac(username: str, session: str, csrf: str, limit: int = 80) -> list[dict]:
    headers = _make_headers(session, csrf)
    payload = {
        "query": RECENT_AC_QUERY,
        "variables": {"userSlug": username, "limit": limit},
    }
    resp = requests.post(LEETCODE_API_URL, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"LeetCode API 返回错误: {data['errors']}")
    return data.get("data", {}).get("recentACSubmissions") or []


def fetch_recent_all(username: str, session: str, csrf: str) -> list[dict]:
    """拉取最近的所有提交（含失败），用于卡点检测。失败时返回空列表。"""
    headers = _make_headers(session, csrf)
    payload = {
        "query": RECENT_ALL_QUERY,
        "variables": {"userSlug": username},
    }
    try:
        resp = requests.post(LEETCODE_API_URL, json=payload, headers=headers, timeout=15)
        data = resp.json()
        return data.get("data", {}).get("recentSubmissions") or []
    except Exception:
        return []


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
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run([
                "osascript", "-e",
                f'display notification "{message}" with title "{title}"',
            ], capture_output=True, timeout=5)
        elif system == "Linux":
            subprocess.run(["notify-send", title, message],
                           capture_output=True, timeout=5)
        elif system == "Windows":
            ps = (
                f"[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                f"$n = New-Object System.Windows.Forms.NotifyIcon; "
                f"$n.Icon = [System.Drawing.SystemIcons]::Information; "
                f"$n.Visible = $true; "
                f"$n.ShowBalloonTip(5000, '{title}', '{message}', 'Info')"
            )
            subprocess.run(["powershell", "-Command", ps],
                           capture_output=True, timeout=5)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# main: sync / status / cron / 可视化命令
# ---------------------------------------------------------------------------


def sync():
    today = datetime.now(CST)
    today_str = today.strftime("%Y-%m-%d")
    today_date = today.date()
    print(f"=== LeetCode Hot100 每日同步 ({today_str}) ===\n")

    ensure_plan_files(PLAN_DIR, PROGRESS_FILE, CHECKIN_FILE, DASHBOARD_FILE)
    creds = ensure_credentials()
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
        send_notification("LeetCode 同步", "今日暂无 AC 提交")
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

    msg = f"新题 {len(new_problems)} 道，复习 {len(review_problems)} 道"
    if hot100_struggles:
        msg += f"，卡点 {len(hot100_struggles)} 道"
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

    schedule.every().day.at(time_str).do(sync)
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
    streak, _ = _compute_streak(CHECKIN_FILE)
    serve_web(rows, stats, checkin_data, streak, port)


def cmd_weakness():
    from .features import print_weakness_analysis
    ensure_plan_files(PLAN_DIR, PROGRESS_FILE, CHECKIN_FILE, DASHBOARD_FILE)
    _, rows = parse_progress_table(PROGRESS_FILE)
    print_weakness_analysis(rows)


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
                        metavar="PORT", help="启动本地 Web 看板（默认端口 8100）")
    parser.add_argument("--weakness", action="store_true",
                        help="分类薄弱点分析")
    parser.add_argument("--report", action="store_true",
                        help="生成每周报告")
    parser.add_argument("--cron", metavar="HH:MM",
                        help="每天定时自动同步")
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
    elif args.cron:
        cron_loop(args.cron)
    else:
        sync()


if __name__ == "__main__":
    main()
