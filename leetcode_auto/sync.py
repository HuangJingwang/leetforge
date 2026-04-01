#!/usr/bin/env python3
"""LeetCode Hot100 每日同步工具

自动获取今日 LeetCode CN 的 AC 记录，筛选 Hot100 题目，
更新刷题进度并检测代码优化空间。
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from .storage import load_json, save_json, load_text, save_text
from .config import (
    DATA_DIR,
    PLAN_DIR,
    PROGRESS_FILE,
    CHECKIN_FILE,
    DASHBOARD_FILE,
    OPTIMIZE_FILE,
    load_plan_config,
    get_ai_config,
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
    fetch_accepted_history,
)

CST = timezone(timedelta(hours=8))
HISTORY_MARKER = "历史"
_HISTORY_SYNC_FILE = DATA_DIR / "history_sync.json"
_LAST_SYNC_FILE = DATA_DIR / "last_sync.json"


def _load_last_sync_time() -> datetime:
    """返回上次同步时间，无记录则返回今日 00:00。"""
    data = load_json(_LAST_SYNC_FILE)
    if data and data.get("time"):
        try:
            return datetime.fromisoformat(data["time"])
        except (ValueError, TypeError):
            pass
    return datetime.now(CST).replace(hour=0, minute=0, second=0, microsecond=0)


def _save_last_sync_time():
    save_json(_LAST_SYNC_FILE, {"time": datetime.now(CST).isoformat()})


class SyncError(Exception):
    """同步过程中不可恢复的错误。"""


@dataclass
class SyncResult:
    """sync() 的结构化返回值，调用方可据此决定后续行为。"""
    success: bool = True
    error: str = ""
    new_count: int = 0
    review_count: int = 0
    struggle_count: int = 0
    optimization_count: int = 0
    imported_count: int = 0


# ---------------------------------------------------------------------------
# 每日打卡
# ---------------------------------------------------------------------------


def _next_day_num(filepath) -> int:
    content = load_text(filepath)
    nums = [int(d) for d in re.findall(r"Day (\d+)", content)]
    return max(nums) + 1 if nums else 1


def _render_checkin_entry(
    today_str: str,
    day_num: int,
    new_problems: list[str],
    review_problems: list[str],
    struggles: list[str],
) -> str:
    new_str = "、".join(new_problems) if new_problems else "无"
    review_str = "、".join(review_problems) if review_problems else "无"
    struggle_str = "、".join(struggles) if struggles else "无"
    total = len(new_problems) + len(review_problems)
    return (
        f"\n## {today_str}（Day {day_num}）\n"
        f"- 新题完成：{new_str}（{len(new_problems)} 题）\n"
        f"- 复习完成：{review_str}（{len(review_problems)} 题）\n"
        f"- 今日总题数：{total}\n"
        f"- 卡点题目：{struggle_str}\n"
        f"- 明日计划：\n"
        f"\n---\n\n"
    )


def _collect_today_progress(rows: list[dict], today_str: str) -> tuple[list[str], list[str]]:
    """汇总整张进度表中今天完成的题目，避免重复同步后打卡数据归零。"""
    new_problems: list[str] = []
    review_problems: list[str] = []

    for row in rows:
        title = _display_title(row["title"])
        if row.get("r1") == today_str:
            new_problems.append(title)
            continue
        if any(row.get(rk) == today_str for rk in ROUND_KEYS[1:]):
            review_problems.append(title)

    return new_problems, review_problems


def _load_history_sync_state() -> dict:
    return load_json(_HISTORY_SYNC_FILE, default={})


def _save_history_sync_state(username: str):
    state = {
        "username": username,
        "problem_list": load_plan_config().get("problem_list", "hot100"),
        "saved_at": datetime.now(CST).isoformat(),
    }
    save_json(_HISTORY_SYNC_FILE, state)


def _needs_history_backfill(username: str) -> bool:
    state = _load_history_sync_state()
    current_list = load_plan_config().get("problem_list", "hot100")
    return (
        state.get("username") != username
        or state.get("problem_list") != current_list
    )


def _backfill_history_progress(rows: list[dict], history_slugs: set[str]) -> list[str]:
    """把历史 AC 回填到 R1，作为整体进度基线，不影响今日 AC 和复习到期。"""
    imported_titles: list[str] = []

    for row in rows:
        slug = row.get("title_slug", "")
        if slug not in history_slugs:
            continue
        if any(_is_round_done(row.get(rk, "")) for rk in ROUND_KEYS):
            continue

        row["r1"] = HISTORY_MARKER
        row["status"] = "进行中"
        row["last_date"] = ""
        imported_titles.append(_display_title(row["title"]))

    return imported_titles


def update_checkin(
    filepath, today_str: str,
    new_problems: list[str], review_problems: list[str],
    struggles: list[str],
):
    content = load_text(filepath)

    pattern = re.compile(
        rf"\n?## {re.escape(today_str)}（Day (\d+)）\n.*?\n---\n\n?",
        re.DOTALL,
    )
    match = pattern.search(content)
    if match:
        day_num = int(match.group(1))
        entry = _render_checkin_entry(
            today_str, day_num, new_problems, review_problems, struggles,
        )
        content = pattern.sub(entry, content, count=1)
        print(f"  今日（{today_str}）打卡记录已更新")
    else:
        day_num = _next_day_num(filepath)
        entry = _render_checkin_entry(
            today_str, day_num, new_problems, review_problems, struggles,
        )
        hint_marker = "> 使用方式"
        if hint_marker in content:
            content = content.replace(hint_marker, entry + hint_marker)
        else:
            content = content.rstrip("\n") + "\n" + entry

    save_text(filepath, content)


# ---------------------------------------------------------------------------
# 进度看板
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

    save_text(filepath, content)


# ---------------------------------------------------------------------------
# 桌面通知
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


# ---------------------------------------------------------------------------
# 同步流水线：各步骤拆分为独立函数
# ---------------------------------------------------------------------------


def _step_fetch_ac(username: str, creds: dict) -> list[dict]:
    """步骤 1：获取最近 AC 记录。失败抛 SyncError。"""
    print(f"1. 正在从 LeetCode CN 获取 {username} 的最近 AC 记录...")
    try:
        return fetch_recent_ac(username, creds["session"], creds["csrf"])
    except Exception as e:
        raise SyncError(f"获取 AC 记录失败: {e}") from e


def _step_backfill_history(
    username: str, creds: dict,
    rows: list[dict], hot100_slugs: set[str],
) -> list[str]:
    """步骤 2：回填历史 AC 基线（首次使用或切换题单时）。"""
    if not _needs_history_backfill(username):
        return []
    print("   正在回填历史 AC 基线...")
    try:
        history_slugs = fetch_accepted_history(
            creds["session"], creds["csrf"], hot100_slugs,
        )
        imported = _backfill_history_progress(rows, history_slugs)
        _save_history_sync_state(username)
        print(
            f"   历史 Hot100 AC {len(history_slugs)} 道，"
            f"本地新增基线 {len(imported)} 道"
        )
        return imported
    except Exception as e:
        print(f"   历史基线回填失败：{e}")
        return []


def _step_detect_struggles(
    username: str, creds: dict, today_subs: list[dict],
) -> list[str]:
    """步骤 4：检测卡点题目。"""
    print("\n4. 正在检测卡点题目...")
    all_subs = fetch_recent_all(username, creds["session"], creds["csrf"])
    ac_slugs = {s["titleSlug"] for s in today_subs}
    struggles = detect_struggles(all_subs, ac_slugs)
    if struggles:
        print(f"   检测到 {len(struggles)} 道卡点题：{', '.join(struggles)}")
    else:
        print("   无卡点题目")
    return struggles


def _step_match_problem_list(
    today_subs: list[dict], hot100_slugs: set[str],
) -> set[str]:
    """步骤 5：筛选题单命中。"""
    print("\n5. 正在筛选题单命中...")
    matched = {s["titleSlug"] for s in today_subs if s["titleSlug"] in hot100_slugs}
    print(f"   今日 AC 中 {len(matched)} 道属于 Hot100")
    return matched


def _build_slug_dates(today_subs: list[dict], matched_slugs: set[str]) -> dict[str, str]:
    """从提交记录构建 {slug: 实际AC日期} 映射。"""
    slug_dates = {}
    for sub in today_subs:
        slug = sub["titleSlug"]
        if slug in matched_slugs and slug not in slug_dates:
            ts = datetime.fromtimestamp(int(sub["timestamp"]), tz=CST)
            slug_dates[slug] = ts.strftime("%Y-%m-%d")
    return slug_dates


def _step_update_progress_table(
    rows: list[dict], header_lines: list[str],
    today_subs: list[dict], matched_slugs: set[str],
) -> tuple[list[str], list[str], list[dict]]:
    """步骤 6：更新进度表，使用每道题的实际 AC 日期。"""
    print("\n6. 正在更新进度表...")
    slug_dates = _build_slug_dates(today_subs, matched_slugs)
    new_problems, review_problems, filled_rounds = update_progress(rows, slug_dates)
    write_progress_table(PROGRESS_FILE, header_lines, rows)
    print(f"   新题 {len(new_problems)} 道：{', '.join(new_problems) or '无'}")
    print(f"   复习 {len(review_problems)} 道：{', '.join(review_problems) or '无'}")
    return new_problems, review_problems, filled_rounds


def _step_update_checkin(
    rows: list[dict], today_str: str,
    struggles: list[str], matched_slugs: set[str],
) -> tuple[list[str], list[str]]:
    """步骤 7：更新每日打卡。"""
    print("\n7. 正在更新每日打卡...")
    hot100_struggles = [s for s in struggles if any(
        s == _display_title(r["title"]) for r in rows if r["title_slug"] in matched_slugs
    )]
    today_new, today_review = _collect_today_progress(rows, today_str)
    update_checkin(CHECKIN_FILE, today_str, today_new, today_review, hot100_struggles)
    print("   已写入打卡记录")
    return today_new, today_review


def _step_update_dashboard(
    rows: list[dict], today_new: list[str], today_review: list[str],
) -> list[dict]:
    """步骤 8：更新进度看板。"""
    print("\n8. 正在更新进度看板...")
    today_count = len(today_new) + len(today_review)
    review_due = _get_review_due(rows, datetime.now(CST).date())
    update_dashboard(DASHBOARD_FILE, rows, today_count, review_due)
    stats = _compute_stats(rows)
    print(f"   已完成轮次 {stats['done_rounds']}/{stats['total_rounds']}（{stats['rate']:.1f}%）")
    if review_due:
        print(f"   明日待复习：{len(review_due)} 题")
    return review_due


def _step_analyze_optimizations(
    creds: dict, today_subs: list[dict], matched_slugs: set[str],
    today_str: str,
) -> list[dict]:
    """步骤 9：分析提交代码优化空间 + AI 深度分析。"""
    print("\n9. 正在分析提交代码优化空间...")
    hot100_today_subs = [s for s in today_subs if s["titleSlug"] in matched_slugs]
    optimizations = analyze_submissions_for_optimization(
        creds["session"], creds["csrf"], hot100_today_subs,
    )
    if not optimizations:
        print("   所有提交性能表现良好，无需优化")
        return []

    ai_config = get_ai_config()
    if ai_config["enabled"]:
        print(f"\n10. AI 深度分析（{ai_config['provider']}/{ai_config['model']}）...")
        from .ai_analyzer import batch_analyze
        optimizations = batch_analyze(
            optimizations, creds["session"], creds["csrf"],
        )

    update_optimize_file(OPTIMIZE_FILE, optimizations, today_str)
    opt_titles = [o["title"] for o in optimizations]
    print(f"   检测到 {len(optimizations)} 道题有优化空间：{', '.join(opt_titles)}")
    return optimizations


def _step_per_round_ai(
    creds: dict, filled_rounds: list[dict],
    today_subs: list[dict], today_str: str,
    step_num: int,
):
    """步骤 N：逐题逐轮 AI 分析（独立于业务逻辑，纯 AI 调用）。"""
    ai_cfg = get_ai_config()
    if not ai_cfg["enabled"] or not filled_rounds:
        return

    print(f"\n{step_num}. 逐题 AI 分析（{len(filled_rounds)} 道）...")
    from .ai_analyzer import call_ai, get_last_ai_error, AI_CALL_INTERVAL
    from .problem_data import add_ai_review

    sub_map = {s["titleSlug"]: s for s in today_subs}
    for i, fr in enumerate(filled_rounds):
        if i > 0:
            time.sleep(AI_CALL_INTERVAL)
        slug, rk, title = fr["slug"], fr["round"], fr["title"]
        sub = sub_map.get(slug)
        if not sub:
            continue
        try:
            detail = fetch_submission_detail(
                creds["session"], creds["csrf"], str(sub["id"]),
            )
            code = detail.get("code", "")
            lang = detail.get("lang") or ""
            if not code:
                continue
            prompt = (
                f"请对以下 LeetCode 题目 {title}（第 {rk.upper()} 轮复习）的代码进行全面 Code Review。\n\n"
                f"```{lang.lower()}\n{code}\n```\n\n"
                f"请按以下维度逐项点评（每项 1-2 句话，没有问题就说「无问题」）：\n"
                f"1. **正确性**：代码逻辑是否正确，是否有边界情况遗漏或潜在 bug\n"
                f"2. **时间/空间复杂度**：当前复杂度是多少，是否有更优解法\n"
                f"3. **代码质量**：是否有未使用的变量、冗余代码、命名不清晰、逻辑可简化的地方\n"
                f"4. **更优解法**：是否存在更好的算法思路（简要说明即可）\n"
                f"5. **一句话总结**：这段代码的整体评价和最值得改进的一点\n\n"
                f"请用中文回答，简洁直接。"
            )
            analysis = call_ai(prompt, ai_cfg)
            if analysis:
                add_ai_review(slug, rk, today_str, analysis)
                print(f"   [{rk.upper()}] {title} ✓")
            else:
                print(f"   [{rk.upper()}] {title} ✗ {get_last_ai_error() or '分析失败'}")
        except Exception as e:
            print(f"   [{rk.upper()}] {title} ✗ {e}")


# ---------------------------------------------------------------------------
# 主入口：薄编排层
# ---------------------------------------------------------------------------


def _flush_imported(header_lines: list[str], rows: list[dict], imported_titles: list[str]):
    """如果有历史回填但无今日 AC，仍需写盘。"""
    if imported_titles:
        write_progress_table(PROGRESS_FILE, header_lines, rows)
        review_due = _get_review_due(rows, datetime.now(CST).date())
        update_dashboard(DASHBOARD_FILE, rows, 0, review_due)


def sync(interactive: bool = True, quiet: bool = False) -> SyncResult:
    """主同步入口。返回 SyncResult，不再调用 sys.exit。

    quiet: 为 True 时不发送桌面通知（用于定时后台同步）。
    """
    today = datetime.now(CST)
    today_str = today.strftime("%Y-%m-%d")
    result = SyncResult()
    print(f"=== LeetCode Hot100 每日同步 ({today_str}) ===\n")

    ensure_plan_files(PLAN_DIR, PROGRESS_FILE, CHECKIN_FILE, DASHBOARD_FILE)
    creds = ensure_credentials(interactive=interactive)
    if not creds:
        if not quiet:
            send_notification("LeetCode 同步失败", "Cookie 已过期，请运行 leetcode --login")
        return SyncResult(success=False, error="Cookie 过期")
    username = creds["username"]

    # 1. 获取 AC 记录
    try:
        all_ac = _step_fetch_ac(username, creds)
    except SyncError as e:
        print(f"   {e}")
        send_notification("LeetCode 同步失败", str(e))
        return SyncResult(success=False, error=str(e))

    # 2. 解析进度表 + 回填历史
    print("\n2. 正在解析进度表...")
    header_lines, rows = parse_progress_table(PROGRESS_FILE)
    hot100_slugs = {r["title_slug"] for r in rows if r["title_slug"]}
    imported_titles = _step_backfill_history(username, creds, rows, hot100_slugs)
    result.imported_count = len(imported_titles)

    # 3. 筛选自上次同步以来的 AC
    since = _load_last_sync_time()
    today_subs = filter_today_ac(all_ac, since=since)
    if since.date() < today.date():
        print(f"\n3. 自 {since.strftime('%m-%d %H:%M')} 以来共 {len(today_subs)} 道 AC 提交（补同步）")
    else:
        print(f"\n3. 今日共 {len(today_subs)} 道 AC 提交")
    if not today_subs:
        _flush_imported(header_lines, rows, imported_titles)
        _save_last_sync_time()
        print("\n今日暂无 AC 提交，无需更新。")
        return result

    # 4. 检测卡点
    struggles = _step_detect_struggles(username, creds, today_subs)
    result.struggle_count = len(struggles)

    # 5. 筛选题单
    matched_slugs = _step_match_problem_list(today_subs, hot100_slugs)
    if not matched_slugs:
        _flush_imported(header_lines, rows, imported_titles)
        _save_last_sync_time()
        print("\n今日 AC 题目均不在 Hot100 范围内，无需更新。")
        return result

    # 6. 更新进度表（使用每道题的实际 AC 日期）
    new_problems, review_problems, filled_rounds = _step_update_progress_table(
        rows, header_lines, today_subs, matched_slugs,
    )

    # 7. 更新打卡
    today_new, today_review = _step_update_checkin(
        rows, today_str, struggles, matched_slugs,
    )
    result.new_count = len(today_new)
    result.review_count = len(today_review)

    # 8. 更新看板
    _step_update_dashboard(rows, today_new, today_review)

    # 9-10. 优化分析 + AI 深度分析
    optimizations = _step_analyze_optimizations(
        creds, today_subs, matched_slugs, today_str,
    )
    result.optimization_count = len(optimizations)

    # 11. 逐题 AI 分析（AI 逻辑与业务数据完全分离）
    step_num = 11 if optimizations else 10
    _step_per_round_ai(creds, filled_rounds, today_subs, today_str, step_num)

    # 通知（定时同步不弹通知）
    if not quiet:
        msg = f"新题 {result.new_count} 道，复习 {result.review_count} 道"
        if struggles:
            msg += f"，卡点 {result.struggle_count} 道"
        if optimizations:
            msg += f"，{result.optimization_count} 道待优化"
        send_notification("LeetCode 同步完成", msg)

    _save_last_sync_time()
    print("\n=== 同步完成 ===")
    return result
