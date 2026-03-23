#!/usr/bin/env python3
"""LeetCode Hot100 每日同步工具

自动获取今日 LeetCode CN 的 AC 记录，筛选 Hot100 题目，
更新刷题进度并检测代码优化空间。
"""

import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta

from .config import (
    PLAN_DIR,
    PROGRESS_FILE,
    CHECKIN_FILE,
    DASHBOARD_FILE,
    OPTIMIZE_FILE,
)
from .progress import (
    ROUND_KEYS, REVIEW_INTERVALS,
    parse_progress_table, write_progress_table,
    _display_title, _is_round_done,
    update_progress, _get_review_due,
    _compute_stats,
    update_optimize_file,
)
from .init_plan import ensure_plan_files
from .leetcode_api import (
    ensure_credentials,
    fetch_recent_ac, fetch_recent_all, filter_today_ac, detect_struggles,
    fetch_submission_detail,
    analyze_submissions_for_optimization,
)

CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# 每日打卡
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
        f"- 总轮次数：{stats['total_rounds']}（{stats['total']}×{len(ROUND_KEYS)}）\n"
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
                       "-group", "offerpilot"]
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
    new_problems, review_problems, filled_rounds = update_progress(rows, matched_slugs, today_str)
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

    # 每道题逐轮 AI 分析
    from .config import get_ai_config
    ai_cfg = get_ai_config()
    if ai_cfg["enabled"] and filled_rounds:
        step = 9 if optimizations else 8
        print(f"\n{step}. 逐题 AI 分析（{len(filled_rounds)} 道）...")
        from .ai_analyzer import call_ai
        from .problem_data import add_ai_review
        sub_map = {s["titleSlug"]: s for s in today_subs}
        for fr in filled_rounds:
            slug = fr["slug"]
            rk = fr["round"]
            title = fr["title"]
            sub = sub_map.get(slug)
            if not sub:
                continue
            try:
                detail = fetch_submission_detail(creds["session"], creds["csrf"], str(sub["id"]))
                code = detail.get("code", "")
                lang = (detail.get("lang") or {}).get("name", "")
                if not code:
                    continue
                prompt = (
                    f"请简要分析以下 LeetCode 题目 {title}（{rk.upper()}）的代码，"
                    f"指出可优化的点和改进方向（100字以内）：\n\n```{lang.lower()}\n{code}\n```"
                )
                analysis = call_ai(prompt, ai_cfg)
                if analysis:
                    add_ai_review(slug, rk, today_str, analysis)
                    print(f"   [{rk.upper()}] {title} ✓")
            except Exception:
                continue

    msg = f"新题 {len(new_problems)} 道，复习 {len(review_problems)} 道"
    if hot100_struggles:
        msg += f"，卡点 {len(hot100_struggles)} 道"
    if optimizations:
        msg += f"，{len(optimizations)} 道待优化"
    send_notification("LeetCode 同步完成", msg)

    print("\n=== 同步完成 ===")


