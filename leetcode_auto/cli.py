#!/usr/bin/env python3
"""LeetCode Hot100 每日同步工具 — CLI 入口

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
import os
import signal
import sys
import time
from datetime import date

from .sync import sync
from .sync import send_notification
from .config import (
    PLAN_DIR,
    PROGRESS_FILE,
    CHECKIN_FILE,
    DASHBOARD_FILE,
    OPTIMIZE_FILE,
)
from .progress import (
    ROUND_KEYS,
    parse_progress_table,
    _display_title, _is_round_done,
    _get_review_due,
    _compute_stats, _compute_streak, _estimate_completion,
    _load_optimizations,
)
from .init_plan import ensure_plan_files
from .leetcode_api import browser_login


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
        for rk in ROUND_KEYS:
            label = rk.upper()
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
    from .ai_analyzer import (
        build_chat_context, chat, load_chat_history,
        save_chat_history, clear_chat_history,
    )

    ai_config = get_ai_config()
    if not ai_config["enabled"]:
        print("错误：未配置 AI。请在 ~/.leetcode_auto/.env 中设置：")
        print("  AI_PROVIDER=openai")
        print("  AI_API_KEY=sk-xxx")
        sys.exit(1)

    print(f"=== BrushUp AI 助手（{ai_config['model']}）===")
    print("输入问题即可对话，输入 q 退出，输入 clear 清空历史\n")

    system_prompt = build_chat_context()
    history = load_chat_history()

    if history:
        print(f"（已加载 {len(history) // 2} 轮历史对话）\n")

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
        if user_input.lower() == "clear":
            history = []
            clear_chat_history()
            print("已清空对话历史。\n")
            continue

        reply = chat(user_input, history, system_prompt)
        if reply:
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": reply})
            save_chat_history(history)
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
        is_background = os.environ.get("BRUSHUP_DAEMON") == "1"
        sync(interactive=not is_background)


if __name__ == "__main__":
    main()
