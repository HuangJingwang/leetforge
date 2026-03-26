"""可视化与高级分析功能：Rich TUI、热力图、SVG 徽章、薄弱点分析、周报。"""

import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .init_plan import SLUG_CATEGORY

# ---------------------------------------------------------------------------
# 共享数据解析
# ---------------------------------------------------------------------------

from .config import get_round_keys
ROUND_KEYS = get_round_keys()


def _is_done(val: str) -> bool:
    return bool(val) and val not in ("", "—")


def _display_title(raw_title: str) -> str:
    m = re.search(r"\[(.+?)\]", raw_title)
    return m.group(1) if m else raw_title


def _supports_unicode_output() -> bool:
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in encoding or encoding == "cp65001"


def parse_checkin_data(filepath) -> list[dict]:
    """从打卡文件解析每日数据，返回 [{date, new, review, total}]。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return []

    entries = []
    blocks = re.split(r"(?=## \d{4}-\d{2}-\d{2})", content)
    for block in blocks:
        dm = re.match(r"## (\d{4}-\d{2}-\d{2})", block)
        if not dm:
            continue
        d = datetime.strptime(dm.group(1), "%Y-%m-%d").date()
        new_m = re.search(r"新题完成：.*?（(\d+) 题）", block)
        rev_m = re.search(r"复习完成：.*?（(\d+) 题）", block)
        tot_m = re.search(r"今日总题数：(\d+)", block)
        new_c = int(new_m.group(1)) if new_m else 0
        rev_c = int(rev_m.group(1)) if rev_m else 0
        tot_c = int(tot_m.group(1)) if tot_m else new_c + rev_c
        entries.append({"date": d, "new": new_c, "review": rev_c, "total": tot_c})
    entries.sort(key=lambda x: x["date"])
    return entries


def compute_category_stats(rows: list[dict]) -> dict[str, dict]:
    """按算法分类统计完成率，返回 {category: {total, done_r1, done_all}}。"""
    cat_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "done_r1": 0, "done_all": 0})
    for row in rows:
        cat = SLUG_CATEGORY.get(row.get("title_slug", ""), "其他")
        cat_stats[cat]["total"] += 1
        if _is_done(row["r1"]):
            cat_stats[cat]["done_r1"] += 1
        if all(_is_done(row[rk]) for rk in ROUND_KEYS):
            cat_stats[cat]["done_all"] += 1
    return dict(cat_stats)


# ---------------------------------------------------------------------------
# 1. Rich TUI
# ---------------------------------------------------------------------------


def rich_status(rows, stats, review_due, streak, total_days, est, checkin_data):
    """用 rich 库渲染炫彩终端面板。"""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text
        from rich import box
    except ImportError:
        print("提示：安装 rich 可获得更好的视觉体验  pip install rich")
        return False

    if not _supports_unicode_output():
        return False

    console = Console()
    console.print()

    title_text = Text("🎯 LeetCode Hot100 刷题进度", style="bold cyan")
    console.print(Panel(title_text, box=box.DOUBLE_EDGE, style="cyan"))

    # --- 总览 ---
    overview = Table(show_header=False, box=None, padding=(0, 2))
    overview.add_column(style="bold")
    overview.add_column()
    overview.add_row("题目总数", str(stats["total"]))
    overview.add_row("已完成轮次", f"{stats['done_rounds']}/{stats['total_rounds']} ({stats['rate']:.1f}%)")
    overview.add_row("5轮全通", f"{stats['done_problems']}/{stats['total']}")
    overview.add_row("连续打卡", f"{streak} 天 🔥" if streak >= 3 else f"{streak} 天")
    overview.add_row("累计打卡", f"{total_days} 天")
    overview.add_row("预估完成", est)
    console.print(Panel(overview, title="[bold]总览", border_style="blue"))

    # --- 各轮进度 ---
    progress_table = Table(box=box.SIMPLE_HEAVY, show_edge=False)
    progress_table.add_column("轮次", style="bold", width=4)
    progress_table.add_column("进度条", width=30)
    progress_table.add_column("完成", justify="right", width=10)

    colors = ["green", "yellow", "blue", "magenta", "red", "cyan", "white"]
    for i, rk in enumerate(ROUND_KEYS):
        done = stats["per_round"][rk]
        total = stats["total"]
        pct = done / total if total else 0
        bar_len = 25
        filled = int(pct * bar_len)
        color = colors[i % len(colors)]
        label = rk.upper()
        bar = f"[{color}]{'━' * filled}[/{color}][dim]{'─' * (bar_len - filled)}[/dim]"
        progress_table.add_row(label, bar, f"{done}/{total}")

    console.print(Panel(progress_table, title="[bold]各轮进度", border_style="green"))

    # --- 分类薄弱点 ---
    cat_stats = compute_category_stats(rows)
    if cat_stats:
        cat_table = Table(box=box.SIMPLE, show_edge=False)
        cat_table.add_column("分类", style="bold", width=10)
        cat_table.add_column("R1完成", width=20)
        cat_table.add_column("比率", justify="right", width=8)

        sorted_cats = sorted(cat_stats.items(), key=lambda x: x[1]["done_r1"] / max(x[1]["total"], 1))
        for cat_name, cs in sorted_cats:
            pct = cs["done_r1"] / cs["total"] if cs["total"] else 0
            bar_len = 12
            filled = int(pct * bar_len)
            if pct < 0.3:
                color = "red"
            elif pct < 0.7:
                color = "yellow"
            else:
                color = "green"
            bar = f"[{color}]{'█' * filled}[/{color}][dim]{'░' * (bar_len - filled)}[/dim]"
            cat_table.add_row(cat_name, bar, f"{cs['done_r1']}/{cs['total']}")

        console.print(Panel(cat_table, title="[bold]分类薄弱点（R1完成率 ↑）", border_style="yellow"))

    # --- 复习提醒 ---
    if review_due:
        review_table = Table(box=box.SIMPLE, show_edge=False)
        review_table.add_column("轮次", style="bold cyan", width=4)
        review_table.add_column("题目", width=30)
        review_table.add_column("状态", justify="right", width=14)

        for it in review_due[:10]:
            if it["overdue"] > 3:
                style = "[bold red]逾期 {} 天[/bold red]"
            elif it["overdue"] > 0:
                style = "[yellow]逾期 {} 天[/yellow]"
            else:
                style = "[green]今日到期[/green]"
            status_text = style.format(it["overdue"]) if it["overdue"] > 0 else "[green]今日到期[/green]"
            review_table.add_row(it["round"], it["title"], status_text)

        if len(review_due) > 10:
            review_table.add_row("", f"...等共 {len(review_due)} 题", "")
        console.print(Panel(review_table, title=f"[bold]今日到期复习（{len(review_due)} 题）", border_style="red"))
    else:
        console.print(Panel("[green]今日无到期复习题目 ✓[/green]", border_style="green"))

    # --- 新题建议 ---
    r1_todo = [_display_title(r["title"]) for r in rows if not _is_done(r["r1"])][:5]
    if r1_todo:
        todo_text = "\n".join(f"  [dim]•[/dim] {t}" for t in r1_todo)
        console.print(Panel(todo_text, title="[bold]R1 新题建议", border_style="magenta"))

    console.print()
    return True


# ---------------------------------------------------------------------------
# 2. GitHub 风格热力图
# ---------------------------------------------------------------------------


def render_heatmap(checkin_data: list[dict], weeks: int = 26):
    """在终端渲染 GitHub 风格的刷题热力图。"""
    if not _supports_unicode_output():
        _render_heatmap_plain(checkin_data, weeks)
        return

    try:
        from rich.console import Console
        from rich.text import Text
        from rich.panel import Panel
        from rich import box
    except ImportError:
        _render_heatmap_plain(checkin_data, weeks)
        return

    console = Console()
    date_counts: dict[date, int] = {e["date"]: e["total"] for e in checkin_data}

    today = date.today()
    total_days = weeks * 7
    start = today - timedelta(days=total_days - 1)
    start = start - timedelta(days=start.weekday())

    levels = [
        ("dim", "░"),
        ("green", "▒"),
        ("bold green", "▓"),
        ("bold bright_green", "█"),
    ]

    day_labels = ["Mon", "   ", "Wed", "   ", "Fri", "   ", "Sun"]
    month_header = Text("     ")
    current_month = -1

    d = start
    while d <= today:
        if d.day <= 7 and d.month != current_month:
            m_name = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.month - 1]
            month_header.append(m_name + " ", style="dim")
            current_month = d.month
        elif d.weekday() == 0:
            month_header.append("  ")
        d += timedelta(days=7)

    grid_rows = []
    for dow in range(7):
        row = Text(f" {day_labels[dow]} ")
        d = start + timedelta(days=dow)
        while d <= today:
            count = date_counts.get(d, 0)
            if count == 0:
                style, char = levels[0]
            elif count <= 2:
                style, char = levels[1]
            elif count <= 4:
                style, char = levels[2]
            else:
                style, char = levels[3]

            if d > today:
                row.append(" ", style="dim")
            else:
                row.append(char, style=style)
            row.append(" ")
            d += timedelta(days=7)
        grid_rows.append(row)

    console.print()
    legend = Text()
    legend.append("  Less ", style="dim")
    for style, char in levels:
        legend.append(char + " ", style=style)
    legend.append("More", style="dim")

    content = Text()
    content.append(month_header)
    content.append("\n")
    for row in grid_rows:
        content.append(row)
        content.append("\n")
    content.append("\n")
    content.append(legend)

    console.print(Panel(content, title="[bold]刷题热力图（近 6 个月）", border_style="green", box=box.ROUNDED))
    console.print()


def _render_heatmap_plain(checkin_data, weeks=26):
    """无 rich 时的纯文本热力图。"""
    date_counts = {e["date"]: e["total"] for e in checkin_data}
    today = date.today()
    total_days = weeks * 7
    start = today - timedelta(days=total_days - 1)
    start = start - timedelta(days=start.weekday())

    chars = [".", ":", "*", "#"]
    day_labels = ["Mon", "   ", "Wed", "   ", "Fri", "   ", "Sun"]

    print(f"\n=== 刷题热力图（近 {weeks} 周）===\n")
    for dow in range(7):
        line = f" {day_labels[dow]} "
        d = start + timedelta(days=dow)
        while d <= today:
            count = date_counts.get(d, 0)
            idx = min(count, 3) if count > 0 else 0
            line += chars[idx] + " "
            d += timedelta(days=7)
        print(line)
    print("\n . 0题  : 1-2题  * 3-4题  # 5+题\n")


# ---------------------------------------------------------------------------
# 3. SVG 进度徽章
# ---------------------------------------------------------------------------

_BADGE_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img">
  <title>LeetCode Hot100: {value}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="{width}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_w}" height="20" fill="#555"/>
    <rect x="{label_w}" width="{value_w}" height="20" fill="{color}"/>
    <rect width="{width}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text x="{label_x}" y="14" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_x}" y="13">{label}</text>
    <text x="{value_x}" y="14" fill="#010101" fill-opacity=".3">{value}</text>
    <text x="{value_x}" y="13">{value}</text>
  </g>
</svg>"""


def generate_badge(stats: dict, output_path: Optional[Path] = None) -> Path:
    """生成 SVG 进度徽章（shields.io 风格），返回文件路径。"""
    from .config import PLAN_DIR

    rate = stats["rate"]
    done = stats["done_rounds"]
    total = stats["total_rounds"]

    if rate >= 80:
        color = "#4c1"
    elif rate >= 50:
        color = "#97ca00"
    elif rate >= 20:
        color = "#dfb317"
    else:
        color = "#007ec6"

    label = "LeetCode Hot100"
    value = f"{done}/{total} ({rate:.1f}%)"
    label_w = 110
    value_w = 120
    width = label_w + value_w

    svg = _BADGE_TEMPLATE.format(
        width=width, label_w=label_w, value_w=value_w, color=color,
        label=label, value=value,
        label_x=label_w // 2, value_x=label_w + value_w // 2,
    )

    if output_path is None:
        output_path = PLAN_DIR / "progress_badge.svg"
    output_path.write_text(svg, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# 4. 分类薄弱点分析（终端版）
# ---------------------------------------------------------------------------


def print_weakness_analysis(rows):
    """独立的薄弱点分析命令，带终端雷达图近似。"""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich import box
        has_rich = True
    except ImportError:
        has_rich = False

    if has_rich and not _supports_unicode_output():
        has_rich = False

    cat_stats = compute_category_stats(rows)
    sorted_cats = sorted(cat_stats.items(), key=lambda x: x[1]["done_r1"] / max(x[1]["total"], 1))

    if has_rich:
        console = Console()
        console.print()

        table = Table(title="分类薄弱点分析", box=box.ROUNDED, show_lines=True)
        table.add_column("分类", style="bold", width=10)
        table.add_column("题数", justify="center", width=4)
        table.add_column("R1 完成率", width=22)
        table.add_column("全通率", width=22)
        table.add_column("建议", width=8)

        for cat_name, cs in sorted_cats:
            r1_pct = cs["done_r1"] / cs["total"] if cs["total"] else 0
            all_pct = cs["done_all"] / cs["total"] if cs["total"] else 0

            r1_bar_len = 12
            r1_filled = int(r1_pct * r1_bar_len)
            all_filled = int(all_pct * r1_bar_len)

            if r1_pct < 0.3:
                r1_c, advice = "red", "⚡ 重点"
            elif r1_pct < 0.7:
                r1_c, advice = "yellow", "📝 加油"
            else:
                r1_c, advice = "green", "✅ 不错"

            all_c = "green" if all_pct > 0.5 else ("yellow" if all_pct > 0.2 else "dim")

            r1_bar = f"[{r1_c}]{'█' * r1_filled}[/{r1_c}][dim]{'░' * (r1_bar_len - r1_filled)}[/dim] {r1_pct:.0%}"
            all_bar = f"[{all_c}]{'█' * all_filled}[/{all_c}][dim]{'░' * (r1_bar_len - all_filled)}[/dim] {all_pct:.0%}"

            table.add_row(cat_name, str(cs["total"]), r1_bar, all_bar, advice)

        console.print(table)

        console.print()
        radar_data = []
        for cat_name, cs in cat_stats.items():
            pct = cs["done_r1"] / cs["total"] if cs["total"] else 0
            radar_data.append((cat_name, pct))
        radar_data.sort(key=lambda x: x[0])

        console.print(Panel(
            _text_radar(radar_data),
            title="[bold]能力雷达",
            border_style="cyan",
        ))
        console.print()
    else:
        print("\n=== 分类薄弱点分析 ===\n")
        for cat_name, cs in sorted_cats:
            r1_pct = cs["done_r1"] / cs["total"] if cs["total"] else 0
            bar = "#" * int(r1_pct * 10) + "-" * (10 - int(r1_pct * 10))
            print(f"  {cat_name:<8} {bar} {r1_pct:.0%} ({cs['done_r1']}/{cs['total']})")
        print()


def _text_radar(data: list[tuple[str, float]]) -> str:
    """生成文本版雷达图近似。"""
    lines = []
    max_bar = 20
    for name, pct in data:
        filled = int(pct * max_bar)
        if pct >= 0.7:
            indicator = "🟢"
        elif pct >= 0.3:
            indicator = "🟡"
        else:
            indicator = "🔴"
        bar = "━" * filled + "─" * (max_bar - filled)
        lines.append(f"  {indicator} {name:<8} {bar} {pct:.0%}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. 每周报告
# ---------------------------------------------------------------------------


def generate_weekly_report(rows, checkin_data: list[dict],
                           stats: dict, target_dir: Optional[Path] = None) -> Path:
    """生成本周周报 Markdown 文件。"""
    from .config import PLAN_DIR

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    last_week_start = week_start - timedelta(days=7)

    this_week = [e for e in checkin_data if week_start <= e["date"] <= week_end]
    last_week = [e for e in checkin_data if last_week_start <= e["date"] < week_start]

    tw_new = sum(e["new"] for e in this_week)
    tw_rev = sum(e["review"] for e in this_week)
    tw_total = sum(e["total"] for e in this_week)
    tw_days = len(this_week)

    lw_total = sum(e["total"] for e in last_week)

    if lw_total > 0:
        change = (tw_total - lw_total) / lw_total * 100
        trend = f"较上周 {'📈 +' if change >= 0 else '📉 '}{change:.0f}%"
    else:
        trend = "上周无数据"

    cat_stats = compute_category_stats(rows)
    weak_cats = sorted(cat_stats.items(),
                       key=lambda x: x[1]["done_r1"] / max(x[1]["total"], 1))[:3]
    weak_text = "\n".join(
        f"- **{c}**：R1 完成 {s['done_r1']}/{s['total']}"
        for c, s in weak_cats
    )

    r1_todo = [_display_title(r["title"]) for r in rows if not _is_done(r["r1"])]
    r1_remain = len(r1_todo)
    r1_suggestions = "\n".join(f"  - {t}" for t in r1_todo[:5])

    content = (
        f"# 周报 {week_start.strftime('%m/%d')} - {week_end.strftime('%m/%d')}\n"
        f"\n"
        f"## 本周概况\n"
        f"| 指标 | 数值 |\n"
        f"|------|------|\n"
        f"| 打卡天数 | {tw_days}/7 |\n"
        f"| 新题完成 | {tw_new} 题 |\n"
        f"| 复习完成 | {tw_rev} 题 |\n"
        f"| 本周总计 | {tw_total} 题 |\n"
        f"| 上周总计 | {lw_total} 题 |\n"
        f"| 趋势 | {trend} |\n"
        f"\n"
        f"## 总体进度\n"
        f"- 已完成轮次：{stats['done_rounds']}/{stats['total_rounds']}（{stats['rate']:.1f}%）\n"
        f"- 5 轮全通：{stats['done_problems']}/{stats['total']}\n"
        f"- R1 剩余：{r1_remain} 题\n"
        f"\n"
        f"## 薄弱分类 TOP 3\n"
        f"{weak_text}\n"
        f"\n"
        f"## 下周建议\n"
        f"- 打卡目标：≥ {max(tw_days + 1, 5)} 天\n"
        f"- 新题建议：\n"
        f"{r1_suggestions}\n"
        f"- 薄弱分类专项突破：{weak_cats[0][0] if weak_cats else '无'}\n"
        f"\n"
        f"> 由 `leetcode --report` 自动生成于 {today.strftime('%Y-%m-%d')}\n"
    )

    if target_dir is None:
        target_dir = PLAN_DIR
    filepath = target_dir / f"周报_{week_start.strftime('%m%d')}-{week_end.strftime('%m%d')}.md"
    filepath.write_text(content, encoding="utf-8")
    return filepath


def push_report(content: str):
    """Push weekly report via webhook and/or email."""
    from .config import WEBHOOK_URL, SMTP_HOST, SMTP_USER, SMTP_PASS, SMTP_TO, SMTP_PORT
    import requests as _req

    sent = False

    # Webhook (Slack / 飞书 / 企微)
    if WEBHOOK_URL:
        try:
            _req.post(WEBHOOK_URL, json={"text": content, "msg_type": "text",
                                          "content": {"text": content}}, timeout=10)
            print("  Webhook sent.")
            sent = True
        except Exception as e:
            print(f"  Webhook failed: {e}")

    # Email
    if SMTP_HOST and SMTP_USER and SMTP_TO:
        try:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText(content, "plain", "utf-8")
            msg["Subject"] = "BrushUp Weekly Report"
            msg["From"] = SMTP_USER
            msg["To"] = SMTP_TO
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.sendmail(SMTP_USER, [SMTP_TO], msg.as_string())
            print("  Email sent.")
            sent = True
        except Exception as e:
            print(f"  Email failed: {e}")

    if not sent:
        print("  No push method configured. Set WEBHOOK_URL or SMTP_* in ~/.leetcode_auto/.env")
