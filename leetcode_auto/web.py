"""本地 Web 看板：启动 HTTP 服务，展示完整刷题数据。

替代桌面 Markdown 文件，提供交互式 Web 界面查看所有刷题信息：
- 数据概览 Dashboard
- 100 题进度表（筛选 / 搜索）
- 每日打卡时间线
- 代码优化建议
"""

import json
import re
import threading
import webbrowser
from datetime import date
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Optional

from .features import ROUND_KEYS, compute_category_stats
from .config import load_plan_config, save_plan_config
from datetime import timedelta
from .init_plan import SLUG_CATEGORY

# Avoid concurrent browser-login flows from duplicate clicks or repeated requests.
_LOGIN_LOCK = threading.Lock()
_LOGIN_RUNNING = False

# ---------------------------------------------------------------------------
# 数据构建
# ---------------------------------------------------------------------------


def _compute_trends(checkin_data: list) -> dict:
    """计算周/月趋势统计。"""
    if not checkin_data:
        return {"this_week": 0, "last_week": 0, "this_month": 0, "last_month": 0,
                "avg_daily": 0, "week_change": 0}
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    last_week_start = week_start - timedelta(days=7)
    month_start = today.replace(day=1)
    if month_start.month == 1:
        last_month_start = month_start.replace(year=month_start.year - 1, month=12)
    else:
        last_month_start = month_start.replace(month=month_start.month - 1)

    tw = sum(e["total"] for e in checkin_data if e["date"] >= week_start)
    lw = sum(e["total"] for e in checkin_data if last_week_start <= e["date"] < week_start)
    tm = sum(e["total"] for e in checkin_data if e["date"] >= month_start)
    lm = sum(e["total"] for e in checkin_data if last_month_start <= e["date"] < month_start)

    recent_30 = [e for e in checkin_data if e["date"] >= today - timedelta(days=30)]
    avg = sum(e["total"] for e in recent_30) / max(len(recent_30), 1)
    change = ((tw - lw) / max(lw, 1) * 100) if lw > 0 else 0

    return {
        "this_week": tw, "last_week": lw,
        "this_month": tm, "last_month": lm,
        "avg_daily": round(avg, 1),
        "week_change": round(change),
    }


def _build_comprehensive_data(
    rows: list,
    stats: dict,
    checkin_data: list,
    streak: int,
    total_days: int,
    review_due: list,
    optimizations: list,
    est: str,
) -> dict:
    """构建前端所需的完整 JSON 数据。"""
    from .problem_data import get_all_problem_data
    cat_stats = compute_category_stats(rows)
    categories = []
    for cat_name, cs in sorted(cat_stats.items(), key=lambda x: x[0]):
        pct = int(cs["done_r1"] / cs["total"] * 100) if cs["total"] else 0
        categories.append([cat_name, pct])

    daily = [
        [e["date"].strftime("%m/%d"), e["new"], e["review"]]
        for e in checkin_data[-60:]
    ]
    heatmap_data = [[e["date"].isoformat(), e["total"]] for e in checkin_data]
    per_round = [stats["per_round"][rk] for rk in ROUND_KEYS]
    today_str = date.today().isoformat()
    today_ac = sum(
        1 for row in rows
        if any((row.get(rk) or "").strip() == today_str for rk in ROUND_KEYS)
    )

    # 构建进度表行数据
    table_rows = []
    for row in rows:
        title_match = re.search(r"\[(.+?)\]", row["title"])
        display_title = title_match.group(1) if title_match else row["title"]
        num_match = re.search(r"\[(\d+)\.", row["title"])
        num = num_match.group(1) if num_match else row["seq"]
        cat = SLUG_CATEGORY.get(row.get("title_slug", ""), "其他")
        table_rows.append({
            "seq": row["seq"],
            "num": num,
            "title": display_title,
            "slug": row.get("title_slug", ""),
            "difficulty": row["difficulty"],
            "category": cat,
            "r1": row["r1"],
            "r2": row["r2"],
            "r3": row["r3"],
            "r4": row["r4"],
            "r5": row["r5"],
            "status": row.get("status", ""),
        })

    # R1 未做的新题 — 按分类分组，优先推荐薄弱分类，同一分类的题集中推荐
    cat_stats = compute_category_stats(rows)
    raw_todo = []
    for row in rows:
        if row["r1"] and row["r1"] not in ("", "—"):
            continue
        title_match = re.search(r"\[(.+?)\]", row["title"])
        display_title = title_match.group(1) if title_match else row["title"]
        cat = SLUG_CATEGORY.get(row.get("title_slug", ""), "其他")
        raw_todo.append({
            "title": display_title,
            "slug": row.get("title_slug", ""),
            "difficulty": row["difficulty"],
            "category": cat,
        })

    # 按分类完成率排序（低完成率优先），同分类内按简单→困难
    diff_order = {"简单": 0, "中等": 1, "困难": 2}
    def _cat_priority(cat_name):
        cs = cat_stats.get(cat_name, {})
        total = cs.get("total", 1)
        done = cs.get("done_r1", 0)
        return done / max(total, 1)  # 完成率越低越优先

    # 先按分类分组（薄弱分类排前面），组内按简单→困难
    from collections import OrderedDict
    sorted_cats = sorted(set(t["category"] for t in raw_todo), key=_cat_priority)
    cat_groups = OrderedDict((c, []) for c in sorted_cats)
    for t in raw_todo:
        cat_groups[t["category"]].append(t)
    for items in cat_groups.values():
        items.sort(key=lambda x: diff_order.get(x["difficulty"], 1))
    new_todo = []
    for items in cat_groups.values():
        new_todo.extend(items)

    # 构建打卡记录
    checkins = []
    for e in reversed(checkin_data):
        checkins.append({
            "date": e["date"].isoformat(),
            "new": e.get("new", 0),
            "review": e.get("review", 0),
            "total": e.get("total", 0),
        })

    return {
        "total": stats["total"],
        "started_problems": stats["per_round"].get("r1", 0),
        "total_rounds": stats["total_rounds"],
        "done_rounds": stats["done_rounds"],
        "done_problems": stats["done_problems"],
        "today_ac": today_ac,
        "rate": round(stats["rate"], 1),
        "per_round": per_round,
        "streak": streak,
        "total_days": total_days,
        "est": est,
        "categories": categories,
        "daily": daily,
        "heatmap_data": heatmap_data,
        "rows": table_rows,
        "checkins": checkins,
        "review_due": [
            {k: (v.isoformat() if isinstance(v, date) else v) for k, v in r.items()}
            for r in review_due
        ],
        "new_todo": new_todo,
        "plan_config": load_plan_config(),
        "ai_usage": __import__('leetcode_auto.ai_analyzer', fromlist=['get_ai_usage']).get_ai_usage(),
        "user_profile": __import__('leetcode_auto.leetcode_api', fromlist=['load_user_profile']).load_user_profile(),
        "trend_stats": _compute_trends(checkin_data),
        "available_lists": {k: {"name": v["name"], "name_en": v["name_en"], "count": len(v["problems"])} for k, v in __import__('leetcode_auto.problem_lists', fromlist=['PROBLEM_LISTS']).PROBLEM_LISTS.items()},
        "problem_data": get_all_problem_data(),
        "optimizations": optimizations,
    }


# ---------------------------------------------------------------------------
# HTML 模板
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeetCode Hot100 刷题看板</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
:root {
  --bg: #0d1117; --bg2: #161b22; --card: #1c2129; --border: #30363d;
  --text: #e6edf3; --dim: #8b949e; --accent: #58a6ff; --green: #3fb950;
  --yellow: #d29922; --red: #f85149; --orange: #f0883e;
  --purple: #a371f7; --pink: #db61a2;
  --transition: .2s ease;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; display:flex; min-height:100vh; }

/* Scrollbar */
::-webkit-scrollbar { width:6px; height:6px; }
::-webkit-scrollbar-track { background:transparent; }
::-webkit-scrollbar-thumb { background:var(--border); border-radius:3px; }
::-webkit-scrollbar-thumb:hover { background:var(--dim); }

/* Transitions */
.tab-content { animation:fadeIn .25s ease; }
@keyframes fadeIn { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }

/* Sidebar */
.sidebar { width:220px; background:var(--bg2); border-right:1px solid var(--border); padding:20px 0; position:fixed; height:100vh; overflow-y:auto; display:flex; flex-direction:column; }
.sidebar h1 { font-size:18px; padding:0 20px 16px; border-bottom:1px solid var(--border); margin-bottom:8px; }
.sidebar h1 span { color:var(--accent); }
.nav-icon { font-size:16px; width:22px; text-align:center; flex-shrink:0; }
.nav-item { display:flex; align-items:center; gap:10px; padding:11px 20px; cursor:pointer; color:var(--dim); transition:all var(--transition); font-size:13px; border-left:3px solid transparent; position:relative; }
.nav-item:hover { background:var(--card); color:var(--text); padding-left:24px; }
.nav-item.active { color:var(--accent); border-left-color:var(--accent); background:rgba(88,166,255,0.06); font-weight:500; }
.nav-item .badge { background:var(--red); color:#fff; font-size:11px; padding:1px 6px; border-radius:10px; margin-left:auto; }
.nav-sep { height:1px; background:var(--border); margin:8px 20px; }
.user-profile { display:flex; align-items:center; gap:10px; padding:10px 20px 14px; border-bottom:1px solid var(--border); margin-bottom:8px; }
.user-avatar { width:32px; height:32px; border-radius:50%; border:2px solid var(--border); object-fit:cover; }
.user-name { font-size:13px; color:var(--text); font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; }
.logout-btn { background:none; border:1px solid var(--border); color:var(--dim); width:26px; height:26px; border-radius:50%; cursor:pointer; font-size:14px; display:flex; align-items:center; justify-content:center; transition:all var(--transition); flex-shrink:0; }
.logout-btn:hover { border-color:var(--red); color:var(--red); }
.login-btn { background:var(--accent); color:#fff; border:none; padding:8px 16px; border-radius:6px; font-size:13px; cursor:pointer; width:100%; transition:opacity var(--transition); }
.login-btn:hover { opacity:0.9; }
.login-btn:disabled { opacity:0.5; cursor:not-allowed; }
.sidebar-footer { margin-top:auto; padding:12px 20px; border-top:1px solid var(--border); }
.sidebar-info { font-size:11px; color:var(--border); }
.lang-toggle { display:flex; gap:4px; margin-top:8px; }
.lang-btn { background:none; border:1px solid var(--border); color:var(--dim); padding:3px 10px; border-radius:4px; font-size:11px; cursor:pointer; }
.lang-btn.active { border-color:var(--accent); color:var(--accent); background:rgba(88,166,255,0.08); }

/* Main */
.main { margin-left:220px; flex:1; padding:24px; max-width:1400px; }
.tab-content { display:none; }
.tab-content.active { display:block; }

/* Stats */
.stats-row { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-bottom:20px; }
.stat-card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:18px 16px; text-align:center; transition:transform var(--transition),box-shadow var(--transition); }
.stat-card:hover { transform:translateY(-2px); box-shadow:0 4px 12px rgba(0,0,0,0.2); }
.stat-card .num { font-size:28px; font-weight:700; color:var(--accent); }
.stat-card .label { font-size:11px; color:var(--dim); margin-top:6px; text-transform:uppercase; letter-spacing:0.5px; }
.stat-card .num.fire { color:var(--orange); }
.stat-card .num-sub { font-size:14px; font-weight:400; color:var(--dim); }
.stat-card .num.num-sm { font-size:14px; font-weight:500; margin-top:6px; }
.stat-card:nth-child(2) .num { color:var(--green); }
.stat-card:nth-child(3) .num { color:var(--purple); }
.stat-card:nth-child(5) .num { color:var(--yellow); }

/* Grid */
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(400px,1fr)); gap:16px; margin-bottom:16px; }
.card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:16px; transition:border-color var(--transition); }
.card:hover { border-color:rgba(88,166,255,0.2); }
.card h2 { font-size:13px; color:var(--dim); margin-bottom:12px; padding-bottom:8px; border-bottom:1px solid var(--border); text-transform:uppercase; letter-spacing:0.5px; font-weight:600; }
.card-full { grid-column:1/-1; }
.chart { width:100%; height:320px; }
.chart-lg { width:100%; height:220px; }

/* Progress Table */
.table-controls { display:flex; gap:12px; margin-bottom:16px; flex-wrap:wrap; align-items:center; }
.table-controls input, .table-controls select {
  background:var(--bg2); border:1px solid var(--border); color:var(--text);
  padding:8px 12px; border-radius:6px; font-size:13px; outline:none;
}
.table-controls input:focus, .table-controls select:focus { border-color:var(--accent); }
.table-controls input { flex:1; min-width:200px; }
.table-controls select { min-width:120px; }
.clear-btn { background:var(--border); color:var(--text); border:none; padding:8px 14px; border-radius:6px; font-size:13px; cursor:pointer; white-space:nowrap; }
.clear-btn:hover { background:var(--red); color:#fff; }
.progress-table { width:100%; border-collapse:collapse; font-size:13px; }
.progress-table th { text-align:left; padding:10px 8px; color:var(--dim); border-bottom:2px solid var(--border); position:sticky; top:0; background:var(--bg); font-weight:600; }
.progress-table td { padding:8px; border-bottom:1px solid var(--border); transition:background var(--transition); }
.progress-table tbody tr:hover { background:rgba(88,166,255,0.06); }
.progress-table tbody tr:nth-child(4n+1) { background:rgba(255,255,255,0.01); }
.progress-table a { color:var(--accent); text-decoration:none; }
.progress-table a:hover { text-decoration:underline; }
.round-cell { text-align:center; min-width:65px; }
.round-done { color:var(--green); font-size:12px; }
.round-empty { color:var(--border); }
.diff-easy { color:var(--green); }
.diff-medium { color:var(--yellow); }
.diff-hard { color:var(--red); }
.status-done { color:var(--green); }
.status-progress { color:var(--accent); }
.cat-tag { font-size:11px; padding:2px 6px; border-radius:4px; background:rgba(88,166,255,0.15); color:var(--accent); }
.table-wrapper { max-height:calc(100vh - 200px); overflow-y:auto; border:1px solid var(--border); border-radius:8px; }
.table-count { font-size:12px; color:var(--dim); }

/* Checkin Timeline */
.timeline { max-width:800px; }
.timeline-item { border-left:2px solid var(--border); padding:0 0 24px 20px; position:relative; margin-left:10px; transition:border-color var(--transition); }
.timeline-item:hover { border-left-color:var(--accent); }
.timeline-item::before { content:''; width:10px; height:10px; background:var(--accent); border-radius:50%; position:absolute; left:-6px; top:4px; transition:transform var(--transition); }
.timeline-item:hover::before { transform:scale(1.3); }
.timeline-item.empty::before { background:var(--border); }
.timeline-date { font-weight:600; color:var(--accent); font-size:14px; }
.timeline-stats { display:flex; gap:16px; margin:8px 0; font-size:13px; }
.timeline-stats span { padding:2px 8px; border-radius:4px; }
.timeline-new { background:rgba(88,166,255,0.15); color:var(--accent); }
.timeline-review { background:rgba(63,185,80,0.15); color:var(--green); }
.timeline-total { background:rgba(139,148,158,0.15); color:var(--dim); }

/* Review Due */
.review-list { list-style:none; }
.review-list li { padding:10px 12px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; transition:background var(--transition); }
.review-list li:hover { background:rgba(88,166,255,0.04); }
.review-list li:last-child { border:none; }
.review-round { font-size:12px; padding:2px 8px; border-radius:4px; background:rgba(88,166,255,0.15); color:var(--accent); }
.overdue { color:var(--red); font-size:12px; }
.due-today { color:var(--green); font-size:12px; }

/* Optimization */
.opt-card { background:var(--bg2); border:1px solid var(--border); border-radius:12px; padding:16px; margin-bottom:12px; transition:border-color var(--transition); }
.opt-card:hover { border-color:rgba(88,166,255,0.2); }
.opt-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
.opt-title { font-weight:600; font-size:15px; }
.opt-lang { font-size:12px; padding:2px 8px; border-radius:4px; background:rgba(139,148,158,0.15); color:var(--dim); }
.opt-metrics { display:flex; gap:20px; margin-bottom:10px; font-size:13px; }
.opt-metric { display:flex; align-items:center; gap:6px; }
.pct-bar { width:80px; height:6px; background:var(--border); border-radius:3px; overflow:hidden; }
.pct-fill { height:100%; border-radius:3px; }
.pct-low { background:var(--red); }
.pct-mid { background:var(--yellow); }
.pct-high { background:var(--green); }
.opt-suggestions { font-size:13px; color:var(--dim); margin-bottom:10px; }
.opt-suggestions li { margin:4px 0 4px 16px; }
.code-toggle { background:none; border:1px solid var(--border); color:var(--accent); padding:4px 12px; border-radius:4px; cursor:pointer; font-size:12px; }
.code-toggle:hover { background:rgba(88,166,255,0.1); }
.code-block { display:none; margin-top:10px; background:var(--bg); border:1px solid var(--border); border-radius:6px; padding:12px; font-family:'SF Mono',Monaco,monospace; font-size:12px; overflow-x:auto; white-space:pre; max-height:400px; overflow-y:auto; line-height:1.5; }
.code-block.show { display:block; }
.ai-section { margin-top:12px; border-top:1px solid var(--border); padding-top:12px; }
.ai-label { font-size:12px; color:var(--accent); font-weight:600; margin-bottom:8px; display:flex; align-items:center; gap:6px; }
.ai-label::before { content:''; display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--accent); }
.ai-content { font-size:13px; line-height:1.7; color:var(--text); }
.ai-content h3 { font-size:13px; color:var(--accent); margin:10px 0 4px; }
.ai-content code { background:var(--bg); padding:1px 5px; border-radius:3px; font-size:12px; }
.ai-content pre { background:var(--bg); border:1px solid var(--border); border-radius:6px; padding:10px; margin:6px 0; font-size:12px; overflow-x:auto; line-height:1.5; }
.ai-content ul,.ai-content ol { margin-left:18px; }
.ai-toggle { background:none; border:1px solid var(--accent); color:var(--accent); padding:4px 12px; border-radius:4px; cursor:pointer; font-size:12px; margin-left:8px; }
.ai-toggle:hover { background:rgba(88,166,255,0.1); }

/* Empty state */
.empty-state { text-align:center; padding:60px 20px; color:var(--dim); }
.empty-state .icon { font-size:40px; margin-bottom:12px; opacity:0.5; }
.empty-state p { font-size:13px; line-height:1.6; }

/* Today Plan */
.today-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }
.today-card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:16px; transition:border-color var(--transition); }
.today-card:hover { border-color:rgba(88,166,255,0.2); }
.today-card h2 { font-size:14px; color:var(--dim); margin-bottom:12px; padding-bottom:8px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; }
.today-card h2 .count { font-size:12px; padding:2px 8px; border-radius:10px; }
.count-accent { background:rgba(88,166,255,0.15); color:var(--accent); }
.count-red { background:rgba(248,81,73,0.15); color:var(--red); }
.today-list { list-style:none; max-height:320px; overflow-y:auto; }
.today-list li { padding:8px 0; border-bottom:1px solid rgba(48,54,61,0.5); display:flex; justify-content:space-between; align-items:center; font-size:13px; }
.today-list li:last-child { border:none; }
.today-list a { color:var(--accent); text-decoration:none; }
.today-list a:hover { text-decoration:underline; }
.today-meta { display:flex; gap:8px; align-items:center; }
.today-meta .tag { font-size:11px; padding:1px 6px; border-radius:3px; }
.tag-review { background:rgba(248,81,73,0.12); color:var(--red); }
.tag-new { background:rgba(88,166,255,0.12); color:var(--accent); }
.tag-cat { background:rgba(139,148,158,0.12); color:var(--dim); }

/* Resume */
.resume-layout { display:grid; grid-template-columns:1fr 1fr; gap:16px; height:calc(100vh - 120px); }
.resume-layout.preview-mode { grid-template-columns:1fr 1fr; }
.resume-preview-wrap { display:none; overflow-y:auto; }
.resume-layout.preview-mode .resume-left { display:none; }
.resume-layout.preview-mode .resume-preview-wrap { display:block; }
.resume-left,.resume-right { display:flex; flex-direction:column; gap:12px; overflow-y:auto; }
.resume-actions { display:flex; gap:8px; flex-wrap:wrap; }
.resume-actions button,.resume-actions a {
  background:var(--card); border:1px solid var(--border); color:var(--text); padding:8px 16px;
  border-radius:6px; font-size:13px; cursor:pointer; text-decoration:none; display:inline-flex; align-items:center; gap:6px;
}
.resume-actions button:hover,.resume-actions a:hover { border-color:var(--accent); color:var(--accent); }
.resume-actions .primary { background:var(--accent); border-color:var(--accent); color:#fff; }
.resume-actions .primary:hover { opacity:0.9; }
.resume-textarea { flex:1; min-height:200px; background:var(--bg); border:1px solid var(--border); color:var(--text); padding:12px; border-radius:8px; font-family:'SF Mono',Monaco,monospace; font-size:13px; line-height:1.6; resize:none; outline:none; }
.resume-textarea:focus { border-color:var(--accent); }
.resume-textarea::placeholder { color:var(--border); }
.resume-analysis { background:var(--card); border:1px solid var(--border); border-radius:8px; padding:16px; overflow-y:auto; line-height:1.7; font-size:14px; }
.resume-analysis h3 { color:var(--accent); font-size:14px; margin:12px 0 4px; }
.resume-analysis h3:first-child { margin-top:0; }
.resume-analysis ul,.resume-analysis ol { margin-left:18px; }
.resume-analysis li { margin:3px 0; }
.resume-analysis strong { color:var(--text); }
.resume-analysis code { background:var(--bg); padding:1px 4px; border-radius:3px; font-size:12px; }
.resume-analysis blockquote { border-left:3px solid var(--accent); padding-left:10px; color:var(--dim); margin:8px 0; }
.resume-chat-box { border-top:1px solid var(--border); padding-top:12px; }
.resume-chat-messages { max-height:300px; overflow-y:auto; margin-bottom:8px; }
.resume-score { display:inline-block; font-size:32px; font-weight:bold; color:var(--accent); }
.resume-empty { text-align:center; padding:40px; color:var(--dim); }
.resume-empty .icon { font-size:40px; margin-bottom:12px; }
/* LapisCV Preview */
.lapis-preview { background:#fff; color:#353a42; border-radius:4px; padding:20mm; font-family:-apple-system,'Noto Sans SC','Source Han Sans CN',sans-serif; font-size:10pt; line-height:1.8; box-shadow:0 0 12px rgba(0,0,0,0.15); min-height:100%; }
.lapis-preview h1 { font-size:16pt; text-align:center; border-bottom:none; color:#353a42; margin:0; line-height:1.5; }
.lapis-preview h2 { font-size:12pt; color:#4870ad; border-bottom:1px solid rgba(72,112,173,0.4); margin-top:2.4mm; margin-bottom:1.9mm; padding:1mm 0; line-height:1; }
.lapis-preview h3 { font-size:10.5pt; color:#353a42; line-height:1.8; margin:0; }
.lapis-preview blockquote { text-align:center; border-left:none; padding:0; margin:0; font-size:9.5pt; color:#353a42; }
.lapis-preview blockquote p { text-align:center; }
.lapis-preview a { color:#4870ad; text-decoration:none; }
.lapis-preview code { background:#f6f8fa; color:#353a42; font-size:10pt; padding:0 3px; border-radius:2px; font-family:'JetBrains Mono',Monaco,monospace; }
.lapis-preview strong { color:#353a42; }
.lapis-preview ul { list-style-type:disc; padding-inline-start:3mm; }
.lapis-preview ol { padding-inline-start:5mm; }
.lapis-preview li { padding-left:1.5mm; margin:0; }
.lapis-preview p { margin:0; }
.lapis-preview div[alt="entry-title"] { display:flex; justify-content:space-between; align-items:center; }
.lapis-preview div[alt="entry-title"] p { color:#666; font-size:9.5pt; }
.lapis-preview img[alt="avatar"] { float:right; width:28mm; height:28mm; border-radius:50%; border:2px solid #dae3ea; object-fit:cover; margin:0 0 0 3mm; }
.preview-toggle { background:var(--card); border:1px solid var(--border); color:var(--accent); padding:8px 16px; border-radius:6px; font-size:13px; cursor:pointer; }
.preview-toggle:hover { border-color:var(--accent); }
.preview-toggle.active { background:var(--accent); color:#fff; }
@media (max-width:768px) { .resume-layout { grid-template-columns:1fr; height:auto; } }

/* Settings */
.settings-form { max-width:600px; }
.settings-group { margin-bottom:20px; }
.settings-group label { display:block; font-size:13px; color:var(--dim); margin-bottom:6px; }
.settings-group input,.settings-group select { background:var(--bg); border:1px solid var(--border); color:var(--text); padding:8px 12px; border-radius:6px; font-size:14px; width:100%; outline:none; }
.settings-group input:focus { border-color:var(--accent); }
.settings-hint { font-size:11px; color:var(--border); margin-top:4px; }
.settings-row { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.settings-save-btn { background:var(--accent); color:#fff; border:none; padding:10px 24px; border-radius:6px; font-size:14px; cursor:pointer; margin-top:8px; }
.settings-save-btn:hover { opacity:0.9; }
.pace-card { background:var(--card); border:1px solid var(--border); border-radius:8px; padding:16px; margin-top:20px; max-width:600px; }
.pace-card h3 { font-size:14px; color:var(--dim); margin-bottom:10px; }
.pace-row { display:flex; justify-content:space-between; padding:6px 0; font-size:13px; border-bottom:1px solid rgba(48,54,61,0.5); }
.pace-row:last-child { border:none; }

/* Interview */
.interview-layout { display:grid; grid-template-columns:1fr 1fr; gap:16px; height:calc(100vh - 120px); }
.interview-left { overflow-y:auto; }
.interview-questions { background:var(--card); border:1px solid var(--border); border-radius:8px; padding:16px; line-height:1.7; font-size:14px; }
.interview-questions h2 { color:var(--accent); font-size:15px; margin:14px 0 6px; }
.interview-questions h2:first-child { margin-top:0; }
.interview-questions ol,.interview-questions ul { margin-left:18px; }
.interview-questions li { margin:4px 0; }
.interview-questions strong { color:var(--text); }
.interview-right { display:flex; flex-direction:column; }
.interview-chat { flex:1; display:flex; flex-direction:column; background:var(--card); border:1px solid var(--border); border-radius:8px; overflow:hidden; }
.interview-chat-header { padding:12px 16px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; font-size:14px; font-weight:600; }
.interview-chat-messages { flex:1; overflow-y:auto; padding:12px 16px; }
.interview-status { font-size:12px; padding:3px 10px; border-radius:12px; }
.status-active { background:rgba(63,185,80,0.15); color:var(--green); }
.status-idle { background:rgba(139,148,158,0.15); color:var(--dim); }
@media (max-width:768px) { .interview-layout { grid-template-columns:1fr; height:auto; } }

/* Chat */
.chat-container { display:flex; flex-direction:column; height:calc(100vh - 120px); }
.chat-messages { flex:1; overflow-y:auto; padding:8px 0; }
.chat-msg { display:flex; margin-bottom:12px; }
.chat-msg.user { justify-content:flex-end; }
.chat-bubble { max-width:78%; padding:10px 14px; border-radius:16px; font-size:14px; line-height:1.6; white-space:pre-wrap; word-break:break-word; animation:fadeIn .2s ease; }
.chat-msg.user .chat-bubble { background:linear-gradient(135deg,var(--accent),#4493f8); color:#fff; border-bottom-right-radius:4px; }
.chat-msg.assistant .chat-bubble { background:var(--card); border:1px solid var(--border); border-bottom-left-radius:4px; }
.chat-msg.assistant .chat-bubble h1,.chat-msg.assistant .chat-bubble h2,.chat-msg.assistant .chat-bubble h3 { font-size:14px; color:var(--accent); margin:10px 0 4px; }
.chat-msg.assistant .chat-bubble h1:first-child,.chat-msg.assistant .chat-bubble h2:first-child,.chat-msg.assistant .chat-bubble h3:first-child { margin-top:0; }
.chat-msg.assistant .chat-bubble p { margin:6px 0; }
.chat-msg.assistant .chat-bubble code { background:var(--bg); padding:1px 5px; border-radius:3px; font-size:12px; font-family:'SF Mono',Monaco,monospace; }
.chat-msg.assistant .chat-bubble pre { background:var(--bg); border:1px solid var(--border); border-radius:6px; padding:10px; margin:8px 0; font-size:12px; overflow-x:auto; line-height:1.5; }
.chat-msg.assistant .chat-bubble pre code { background:none; padding:0; }
.chat-msg.assistant .chat-bubble ul,.chat-msg.assistant .chat-bubble ol { margin:6px 0 6px 20px; }
.chat-msg.assistant .chat-bubble li { margin:3px 0; }
.chat-msg.assistant .chat-bubble table { border-collapse:collapse; margin:8px 0; font-size:13px; }
.chat-msg.assistant .chat-bubble th,.chat-msg.assistant .chat-bubble td { border:1px solid var(--border); padding:4px 10px; }
.chat-msg.assistant .chat-bubble th { background:var(--bg); }
.chat-msg.assistant .chat-bubble strong { color:var(--text); }
.chat-msg.assistant .chat-bubble hr { border:none; border-top:1px solid var(--border); margin:12px 0; }
.chat-msg.assistant .chat-bubble blockquote { border-left:3px solid var(--accent); padding-left:10px; color:var(--dim); margin:8px 0; }
.chat-input-row { display:flex; gap:8px; padding-top:12px; border-top:1px solid var(--border); }
.chat-input-row input { flex:1; background:var(--bg2); border:1px solid var(--border); color:var(--text); padding:10px 14px; border-radius:8px; font-size:14px; outline:none; }
.chat-input-row input:focus { border-color:var(--accent); }
.chat-input-row button { background:var(--accent); color:#fff; border:none; padding:10px 20px; border-radius:8px; font-size:14px; cursor:pointer; transition:all var(--transition); }
.chat-input-row button:hover { opacity:0.9; transform:translateY(-1px); }
.chat-input-row button:active { transform:translateY(0); }
.chat-input-row button:disabled { opacity:0.4; cursor:not-allowed; transform:none; }
.chat-typing { color:var(--dim); font-style:italic; font-size:13px; }

/* Light Theme */
body.light { --bg:#f6f8fa; --bg2:#ffffff; --card:#ffffff; --border:#d0d7de; --text:#1f2328; --dim:#656d76; --accent:#0969da; --green:#1a7f37; --purple:#8250df; --yellow:#9a6700; --red:#cf222e; }
body.light .sidebar { border-right-color:#d0d7de; background:#fff; }
body.light .progress-table th { background:#f6f8fa; }
body.light .stat-card:hover { box-shadow:0 4px 12px rgba(0,0,0,0.08); }
body.light .card:hover { border-color:rgba(9,105,218,0.3); }
body.light .chat-msg.user .chat-bubble { background:linear-gradient(135deg,#0969da,#218bff); }

/* Theme toggle */
.theme-toggle { display:flex; gap:4px; margin-top:4px; }
.theme-btn { background:none; border:1px solid var(--border); color:var(--dim); padding:3px 10px; border-radius:4px; font-size:11px; cursor:pointer; }
.theme-btn.active { border-color:var(--accent); color:var(--accent); background:rgba(88,166,255,0.08); }

/* Achievements */
.achievements-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:12px; }
.achievement-card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px; text-align:center; }
.achievement-card.unlocked { border-color:var(--accent); }
.achievement-icon { font-size:32px; margin-bottom:8px; }
.achievement-name { font-size:13px; font-weight:600; }
.achievement-desc { font-size:11px; color:var(--dim); margin-top:4px; }
.achievement-card.locked { opacity:0.4; }

/* Notes modal */
.note-row { display:none; }
.note-row.show { display:table-row; }
.note-row td { padding:8px 8px 8px 40px !important; background:var(--bg2); }
.note-textarea { width:100%; background:var(--bg); border:1px solid var(--border); color:var(--text); padding:8px; border-radius:6px; font-size:12px; min-height:60px; resize:vertical; outline:none; }
.note-textarea:focus { border-color:var(--accent); }
.note-actions { display:flex; gap:8px; margin-top:6px; align-items:center; }
.note-save-btn { background:var(--accent); color:#fff; border:none; padding:4px 12px; border-radius:4px; font-size:12px; cursor:pointer; }
.note-ai-reviews { margin-top:8px; font-size:12px; color:var(--dim); }
.note-ai-reviews summary { cursor:pointer; color:var(--accent); }

/* Focus mode */
.focus-bar { display:flex; gap:12px; align-items:center; margin-bottom:16px; }
.focus-bar select { background:var(--bg2); border:1px solid var(--border); color:var(--text); padding:6px 10px; border-radius:6px; font-size:13px; }

/* Responsive */
@media (max-width:768px) {
  .sidebar { position:fixed; bottom:0; top:auto; left:0; right:0; width:100%; height:auto; flex-direction:row; border-right:none; border-top:1px solid var(--border); padding:0; z-index:100; overflow-x:auto; }
  .sidebar h1,.nav-sep,.sidebar-footer { display:none; }
  .nav-item { flex-direction:column; padding:8px 12px; font-size:11px; gap:2px; border-left:none; border-top:3px solid transparent; flex-shrink:0; }
  .nav-item.active { border-left:none; border-top-color:var(--accent); }
  .nav-icon { font-size:18px; }
  .nav-item .badge { position:absolute; top:2px; right:2px; font-size:9px; padding:0 4px; }
  .main { margin-left:0; padding:16px 12px 70px; }
  .grid { grid-template-columns:1fr; }
  .stats-row { grid-template-columns:repeat(2,1fr); }
  .today-grid { grid-template-columns:1fr; }
  .chat-container { height:calc(100vh - 160px); }
}

/* Page title */
.page-title { font-size:18px; font-weight:600; margin-bottom:20px; display:flex; align-items:center; gap:10px; }
.page-title .icon { font-size:22px; }
.page-title .table-count { font-size:12px; color:var(--dim); font-weight:400; }
</style>
</head>
<body>

<nav class="sidebar">
  <h1><span>BrushUp</span></h1>
  <div class="user-profile" id="user-profile" style="display:none">
    <img id="user-avatar" alt="" class="user-avatar">
    <span id="user-name" class="user-name"></span>
    <button id="user-logout-btn" class="logout-btn" title="Switch Account">&#8635;</button>
  </div>
  <div class="user-profile" id="user-login-bar" style="display:none">
    <button id="user-login-btn" class="login-btn">Login LeetCode</button>
  </div>
  <div class="nav-item" id="sync-btn-nav" style="display:none;cursor:pointer;">
    <span class="nav-icon">&#128259;</span><span id="sync-btn-text">Sync Now</span>
  </div>
  <div class="nav-sep" id="sync-sep" style="display:none"></div>
  <div class="nav-item active" data-tab="dashboard">
    <span class="nav-icon">&#128200;</span><span data-i18n="nav_dashboard">Dashboard</span>
  </div>
  <div class="nav-item" data-tab="chat">
    <span class="nav-icon">&#128172;</span><span data-i18n="nav_chat">AI Chat</span>
  </div>
  <div class="nav-sep"></div>
  <div class="nav-item" data-tab="progress">
    <span class="nav-icon">&#128221;</span><span data-i18n="nav_progress">Progress</span>
  </div>
  <div class="nav-item" data-tab="review" id="nav-review">
    <span class="nav-icon">&#128214;</span><span data-i18n="nav_review">Review</span>
  </div>
  <div class="nav-item" data-tab="checkin">
    <span class="nav-icon">&#128197;</span><span data-i18n="nav_checkin">Check-in</span>
  </div>
  <div class="nav-item" data-tab="optimize" id="nav-optimize">
    <span class="nav-icon">&#9889;</span><span data-i18n="nav_optimize">Optimize</span>
  </div>
  <div class="nav-sep"></div>
  <div class="nav-item" data-tab="resume">
    <span class="nav-icon">&#128196;</span><span data-i18n="nav_resume">Resume</span>
  </div>
  <div class="nav-item" data-tab="interview">
    <span class="nav-icon">&#127908;</span><span data-i18n="nav_interview">Mock Interview</span>
  </div>
  <div class="nav-sep"></div>
  <div class="nav-item" data-tab="settings">
    <span class="nav-icon">&#9881;</span><span data-i18n="nav_settings">Settings</span>
  </div>
  <div class="sidebar-footer">
    <div class="sidebar-info" data-i18n="data_updated">Data: __TODAY__</div>
    <div class="lang-toggle">
      <button class="lang-btn" id="lang-en" onclick="switchLang('en')">EN</button>
      <button class="lang-btn" id="lang-zh" onclick="switchLang('zh')">中文</button>
    </div>
    <div class="theme-toggle">
      <button class="theme-btn" id="theme-dark" onclick="switchTheme('dark')" data-i18n="theme_dark">Dark</button>
      <button class="theme-btn" id="theme-light" onclick="switchTheme('light')" data-i18n="theme_light">Light</button>
    </div>
  </div>
</nav>

<div class="main">

<!-- ==================== 总览 ==================== -->
<div class="tab-content active" id="tab-dashboard">
  <div class="page-title"><span class="icon">&#127919;</span> <span data-i18n="nav_dashboard">Dashboard</span></div>
  <div class="stats-row">
    <div class="stat-card"><div class="num">__DONE_ROUNDS__<span class="num-sub">/ __TOTAL_ROUNDS__</span></div><div class="label" data-i18n="stat_rounds">Completed Rounds</div></div>
    <div class="stat-card"><div class="num">__RATE__%</div><div class="label" data-i18n="stat_rate">Completion Rate</div></div>
    <div class="stat-card"><div class="num">__TODAY_AC__</div><div class="label" data-i18n="stat_today_ac">Today AC</div></div>
    <div class="stat-card"><div class="num">__DONE_ALL__<span class="num-sub">/ __TOTAL__</span></div><div class="label" data-i18n="stat_pass">5-Round Pass</div></div>
    <div class="stat-card"><div class="num __STREAK_CLASS__">__STREAK__</div><div class="label" data-i18n="stat_streak">Streak Days</div></div>
    <div class="stat-card"><div class="num">__TOTAL_DAYS__</div><div class="label" data-i18n="stat_total_days">Total Days</div></div>
    <div class="stat-card"><div class="num num-sm">__EST__</div><div class="label" data-i18n="stat_est">Est. Completion</div></div>
  </div>
  <div class="today-grid">
    <div class="today-card">
      <h2><span data-i18n="today_new">Today: New</span> <span class="count count-accent" id="new-count"></span></h2>
      <ul class="today-list" id="today-new"></ul>
    </div>
    <div class="today-card">
      <h2><span data-i18n="today_review">Today: Review</span> <span class="count count-red" id="review-count-dash"></span></h2>
      <ul class="today-list" id="today-review"></ul>
    </div>
  </div>
  <div class="grid">
    <div class="card"><h2 data-i18n="card_rate">Completion Rate</h2><div id="gauge" class="chart"></div></div>
    <div class="card"><h2 data-i18n="card_rounds">Round Progress</h2><div id="rounds" class="chart"></div></div>
    <div class="card"><h2 data-i18n="card_radar">Category Radar</h2><div id="radar" class="chart"></div></div>
    <div class="card"><h2 data-i18n="card_trend">Daily Trend</h2><div id="trend" class="chart"></div></div>
    <div class="card card-full"><h2 data-i18n="card_heatmap">Heatmap (365 days)</h2><div id="heatmap" class="chart-lg"></div></div>
    <div class="card card-full"><h2>Trend</h2><div id="trend-stats" style="display:flex;gap:20px;flex-wrap:wrap;padding:8px 0;font-size:14px;"></div></div>
    <div class="card card-full"><h2>Review Calendar (14 days)</h2><div id="review-calendar" style="display:flex;gap:8px;flex-wrap:wrap;"></div></div>
  </div>
</div>

<!-- ==================== 进度表 ==================== -->
<div class="tab-content" id="tab-progress">
  <div class="page-title"><span class="icon">&#128221;</span> <span data-i18n="nav_progress">Progress</span> <span class="table-count" id="table-count"></span></div>
  <div class="table-controls">
    <input type="text" id="search-input" placeholder="Search..." data-i18n="search_ph">
    <select id="filter-difficulty">
      <option value="" data-i18n="diff_all">All Difficulty</option>
      <option value="easy" data-i18n="diff_easy">Easy</option>
      <option value="medium" data-i18n="diff_medium">Medium</option>
      <option value="hard" data-i18n="diff_hard">Hard</option>
    </select>
    <select id="filter-category"><option value="" data-i18n="cat_all">All Categories</option></select>
    <select id="filter-status">
      <option value="" data-i18n="status_all">All Status</option>
      <option value="not-started" data-i18n="status_ns">Not Started</option>
      <option value="in-progress" data-i18n="status_ip">In Progress</option>
      <option value="completed" data-i18n="status_done">Completed</option>
    </select>
    <button id="clear-filters" class="clear-btn" style="display:none;" data-i18n="clear_filter">Clear</button>
    <button id="export-csv-btn" class="clear-btn" data-i18n="export_csv">Export CSV</button>
  </div>
  <div class="table-wrapper">
    <table class="progress-table">
      <thead>
        <tr>
          <th>#</th><th data-i18n="th_title">Title</th><th data-i18n="th_diff">Difficulty</th><th data-i18n="th_cat">Category</th>
          <th class="round-cell">R1</th><th class="round-cell">R2</th>
          <th class="round-cell">R3</th><th class="round-cell">R4</th>
          <th class="round-cell">R5</th><th data-i18n="th_status">Status</th>
        </tr>
      </thead>
      <tbody id="progress-body"></tbody>
    </table>
  </div>
</div>

<!-- ==================== 打卡记录 ==================== -->
<div class="tab-content" id="tab-checkin">
  <div class="page-title"><span class="icon">&#128197;</span> <span data-i18n="nav_checkin">Check-in</span></div>
  <div class="grid">
    <div class="card card-full"><h2 data-i18n="card_checkin_trend">Daily Trend</h2><div id="checkin-trend" class="chart"></div></div>
  </div>
  <div class="timeline" id="checkin-timeline"></div>
</div>

<!-- ==================== 待复习 ==================== -->
<div class="tab-content" id="tab-review">
  <div class="page-title"><span class="icon">&#128214;</span> <span data-i18n="nav_review">Review</span> <span class="table-count" id="review-count"></span></div>
  <div class="card" id="review-card">
    <ul class="review-list" id="review-list"></ul>
  </div>
</div>

<!-- ==================== 代码优化 ==================== -->
<div class="tab-content" id="tab-optimize">
  <div class="page-title"><span class="icon">&#9889;</span> <span data-i18n="nav_optimize">Optimize</span> <span class="table-count" id="opt-count"></span></div>
  <div id="optimize-list"></div>
</div>

<!-- ==================== 简历优化 ==================== -->
<div class="tab-content" id="tab-resume">
  <div class="page-title"><span class="icon">&#128196;</span> <span data-i18n="nav_resume">Resume</span></div>
  <div class="resume-actions" style="margin-bottom:12px">
    <select id="resume-selector" style="min-width:160px"></select>
    <button id="resume-new-btn" style="background:var(--card);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:6px;font-size:13px;cursor:pointer;">+ 新建</button>
    <button id="resume-del-btn" style="background:var(--card);border:1px solid var(--border);color:var(--red);padding:8px 12px;border-radius:6px;font-size:13px;cursor:pointer;">删除</button>
  </div>
  <div class="resume-layout">
    <div class="resume-left">
      <div class="resume-actions">
        <a href="/api/resume/template" download="resume_template.md" data-i18n="resume_dl">Download Template</a>
        <button class="primary" id="resume-analyze-btn" data-i18n="resume_analyze">AI Analyze</button>
        <button id="resume-gen-interview-btn" data-i18n="resume_gen">Generate Questions</button>
        <button id="resume-save-btn" data-i18n="resume_save">Save</button>
        <button class="preview-toggle" id="resume-preview-toggle" data-i18n="resume_preview">Preview</button>
        <button id="resume-versions-btn" style="background:var(--card);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:6px;font-size:13px;cursor:pointer;">History</button>
      </div>
      <textarea class="resume-textarea" id="resume-input" placeholder="Paste resume content (Markdown)...&#10;&#10;Download LapisCV template, fill in, paste here, click Preview." data-i18n="resume_ph"></textarea>
    </div>
    <div class="resume-preview-wrap">
      <div class="lapis-preview" id="resume-preview-content"></div>
    </div>
    <div class="resume-right">
      <div class="resume-analysis" id="resume-analysis">
        <div class="resume-empty">
          <div class="icon">&#128196;</div>
          <p data-i18n="resume_empty">Paste your resume on the left, then click "AI Analyze"</p>
        </div>
      </div>
      <div class="resume-chat-box">
        <div class="resume-chat-messages" id="resume-chat-messages"></div>
        <div class="chat-input-row">
          <input type="text" id="resume-chat-input" placeholder="Ask AI for resume improvement..." autocomplete="off" data-i18n="resume_chat_ph">
          <button id="resume-chat-send" data-i18n="btn_send">Send</button>
          <button id="resume-chat-clear" style="background:var(--border);" data-i18n="btn_clear">Clear</button>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ==================== 模拟面试 ==================== -->
<div class="tab-content" id="tab-interview">
  <div class="page-title"><span class="icon">&#127908;</span> <span data-i18n="nav_interview">Mock Interview</span></div>
  <div class="interview-layout">
    <div class="interview-left">
      <div class="interview-questions" id="interview-questions">
        <div class="resume-empty">
          <div class="icon">&#127908;</div>
          <p data-i18n="interview_empty">Paste resume in "Resume" tab, then click "Generate Questions"</p>
        </div>
      </div>
    </div>
    <div class="interview-right">
      <div class="interview-chat">
        <div class="interview-chat-header">
          <span>AI 面试官</span>
          <span class="interview-status status-idle" id="interview-status" data-i18n="interview_status_idle">Not Started</span>
        </div>
        <div id="interview-report-area" style="display:none;padding:12px 16px;overflow-y:auto;max-height:50%;border-bottom:1px solid var(--border);"></div>
        <div class="interview-chat-messages" id="interview-chat-messages"></div>
        <div class="chat-input-row" style="padding:12px;">
          <button id="interview-start-btn" class="primary" style="padding:10px 16px;" data-i18n="interview_start">Start Interview</button>
          <input type="text" id="interview-chat-input" placeholder="Type your answer..." autocomplete="off" disabled data-i18n="interview_ans_ph">
          <button id="interview-chat-send" disabled data-i18n="btn_send">Send</button>
          <button id="interview-report-btn" style="background:var(--accent);color:#fff;border:none;padding:10px 16px;border-radius:8px;font-size:13px;cursor:pointer;">Report</button>
          <button id="interview-chat-clear" style="background:var(--border);" data-i18n="btn_clear">Clear</button>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ==================== 设置 ==================== -->
<div class="tab-content" id="tab-settings">
  <div class="page-title"><span class="icon">&#9881;</span> <span data-i18n="nav_settings">Settings</span></div>
  <div class="settings-form">
    <div class="settings-group">
      <label data-i18n="settings_list">Problem List</label>
      <select id="set-problem-list"></select>
    </div>
    <div class="settings-row">
      <div class="settings-group">
        <label data-i18n="settings_rounds">Review Rounds</label>
        <input type="number" id="set-rounds" min="2" max="10" value="5">
      </div>
      <div class="settings-group">
        <label data-i18n="settings_deadline">Deadline</label>
        <input type="date" id="set-deadline" value="">
        <div class="settings-hint" data-i18n="settings_deadline_hint">Empty = no limit</div>
      </div>
    </div>
    <div class="settings-group">
      <label data-i18n="settings_intervals">Review Intervals (days)</label>
      <input type="text" id="set-intervals" placeholder="1, 3, 7, 14">
      <div class="settings-hint">R2, R3, R4, ... (comma separated)</div>
    </div>
    <div class="settings-row">
      <div class="settings-group">
        <label data-i18n="settings_daily_new">Daily New Suggestion</label>
        <input type="number" id="set-daily-new" min="1" max="20" value="5">
      </div>
      <div class="settings-group">
        <label data-i18n="settings_daily_review">Daily Review Suggestion</label>
        <input type="number" id="set-daily-review" min="1" max="30" value="10">
      </div>
    </div>
    <button class="settings-save-btn" id="settings-save-btn" data-i18n="settings_save">Save Settings</button>
  </div>
  <div class="pace-card" id="pace-card"></div>
</div>

<!-- ==================== AI 对话 ==================== -->
<div class="tab-content" id="tab-chat">
  <div class="page-title"><span class="icon">&#128172;</span> <span data-i18n="nav_chat">AI Chat</span></div>
  <div class="chat-container">
    <div class="chat-messages" id="chat-messages">
      <div class="chat-msg assistant"><div class="chat-bubble" data-i18n="chat_welcome">Hi! I'm the BrushUp AI assistant. I can help you:<br>- Check study progress<br>- Recommend problems to solve<br>- Analyze weak areas<br>- Create study plans<br>- Answer algorithm questions<br><br>What would you like to know?</div></div>
    </div>
    <div class="chat-input-row">
      <input type="text" id="chat-input" placeholder="Type a question..." autocomplete="off" data-i18n="chat_ph">
      <button id="chat-send" data-i18n="btn_send">Send</button>
      <button id="chat-clear" style="background:var(--border);" data-i18n="btn_clear">Clear</button>
    </div>
  </div>
</div>

</div><!-- /main -->

<script>
// ====== i18n ======
var I18N={
  zh:{
    nav_dashboard:'总览',nav_chat:'AI 对话',nav_progress:'进度表',nav_review:'待复习',
    nav_checkin:'打卡记录',nav_optimize:'代码优化',nav_resume:'简历优化',nav_interview:'模拟面试',
    stat_rounds:'已完成轮次',stat_rate:'完成率',stat_today_ac:'今日 AC',stat_pass:'5 轮全通',
    stat_streak:'连续打卡',stat_total_days:'累计打卡',stat_est:'预估完成',
    today_new:'今日新题',today_review:'今日复习',
    card_rate:'完成率',card_rounds:'各轮进度',card_radar:'分类能力',
    card_trend:'每日趋势',card_heatmap:'刷题热力图（近 365 天）',card_checkin_trend:'每日趋势',
    search_ph:'搜索题目...',diff_all:'全部难度',diff_easy:'简单',diff_medium:'中等',diff_hard:'困难',
    cat_all:'全部分类',status_all:'全部状态',status_ns:'未开始',status_ip:'进行中',status_done:'已完成',
    clear_filter:'清除筛选',table_count:'整体进度 {problems_done}/{problems_total} 题 · 轮次 {done}/{rounds} · 显示 {shown}/{total} 题',
    th_title:'题目',th_diff:'难度',th_cat:'分类',th_status:'状态',
    chart_new:'新题',chart_review:'复习',
    r1_done:'R1 已全部完成！',remaining:'共 {n} 题待完成',
    overdue:'逾期 {n} 天',due_today:'今日到期',
    empty:'暂无数据',no_review:'今日无待复习题目，继续保持！',no_opt:'所有提交性能表现良好，无需优化',
    ai_analysis:'AI 分析',btn_expand:'展开',btn_collapse:'收起',
    runtime:'运行时间：',memory:'内存：',show_code:'查看代码',hide_code:'收起代码',
    resume_dl:'下载简历模板',resume_preview:'预览',resume_edit:'编辑',resume_updated:'> ✅ 简历已更新，请查看左侧编辑器或切换到预览查看效果。',resume_analyze:'AI 分析',resume_gen:'生成面试题',resume_save:'保存',
    resume_saved:'已保存',resume_analyzing:'分析中...',resume_ph:'在此粘贴简历内容（Markdown 格式）...\n\n可下载 LapisCV 模板，填入信息后粘贴，点击 Preview 预览。',
    resume_empty:'在左侧粘贴简历内容，然后点击「AI 分析」',resume_chat_ph:'向 AI 提问改进建议...',
    interview_empty:'在「简历优化」页面粘贴简历后，点击「生成面试题」',
    interview_start:'开始面试',interview_starting:'启动中...',interview_status_idle:'未开始',
    interview_status_active:'进行中',interview_ans_ph:'输入你的回答...',
    interview_gen_ing:'生成中...',interview_confirm_reset:'确定重置模拟面试？',
    chat_welcome:'你好！我是 BrushUp AI 助手，可以帮你：<br>- 查看刷题进度和统计<br>- 推荐今天该刷的题<br>- 分析薄弱环节<br>- 制定学习计划<br>- 解答算法问题<br><br>有什么想问的？',
    chat_ph:'输入问题...',btn_send:'发送',btn_clear:'清空',
    confirm_clear:'确定清空所有对话记录？',confirm_clear_resume:'确定清空简历对话记录？',
    chat_cleared:'对话已清空，有什么想问的？',thinking:'思考中...',net_error:'网络错误',
    analysis_fail:'分析失败',paste_first:'请先粘贴简历内容',
    data_updated:'数据更新：__TODAY__',
    nav_settings:'设置',settings_list:'题单',settings_list_warn:'切换题单将创建新的进度表，已有数据不受影响',
    settings_rounds:'复习轮数',settings_intervals:'复习间隔（天）',
    settings_daily_new:'每日新题建议',settings_daily_review:'每日复习建议',
    settings_deadline:'截止日期',settings_deadline_hint:'留空 = 不限制',
    settings_save:'保存设置',settings_saved:'已保存！需重启 Web 服务生效',
    settings_daily_pace:'每日建议进度',settings_remaining:'剩余',settings_days_left:'剩余天数',
    theme_dark:'深色',theme_light:'浅色',
    nav_achievements:'成就',
    export_csv:'导出 CSV',
    focus_mode:'专项突破',focus_select:'选择薄弱分类',
    notes_ph:'添加笔记...',notes_save:'保存笔记',
    achievement_streak7:'连续打卡 7 天',achievement_streak30:'连续打卡 30 天',
    achievement_r1_all:'R1 全部完成',achievement_r1_half:'R1 完成一半',
    shortcut_hint:'快捷键：1-9 切换标签页',
  },
  en:{
    nav_dashboard:'Dashboard',nav_chat:'AI Chat',nav_progress:'Progress',nav_review:'Review',
    nav_checkin:'Check-in',nav_optimize:'Optimize',nav_resume:'Resume',nav_interview:'Mock Interview',
    stat_rounds:'Completed Rounds',stat_rate:'Completion Rate',stat_today_ac:'Today AC',stat_pass:'5-Round Pass',
    stat_streak:'Streak Days',stat_total_days:'Total Days',stat_est:'Est. Completion',
    today_new:'Today: New',today_review:'Today: Review',
    card_rate:'Completion Rate',card_rounds:'Round Progress',card_radar:'Category Radar',
    card_trend:'Daily Trend',card_heatmap:'Heatmap (365 days)',card_checkin_trend:'Daily Trend',
    search_ph:'Search...',diff_all:'All Difficulty',diff_easy:'Easy',diff_medium:'Medium',diff_hard:'Hard',
    cat_all:'All Categories',status_all:'All Status',status_ns:'Not Started',status_ip:'In Progress',status_done:'Completed',
    clear_filter:'Clear',table_count:'Overall {problems_done}/{problems_total} problems · {done}/{rounds} rounds · Showing {shown}/{total}',
    th_title:'Title',th_diff:'Difficulty',th_cat:'Category',th_status:'Status',
    chart_new:'New',chart_review:'Review',
    r1_done:'R1 all completed!',remaining:'{n} problems remaining',
    overdue:'Overdue {n}d',due_today:'Due today',
    empty:'No data yet',no_review:'No reviews due. Keep it up!',no_opt:'All submissions are well optimized!',
    ai_analysis:'AI Analysis',btn_expand:'Show',btn_collapse:'Hide',
    runtime:'Runtime: ',memory:'Memory: ',show_code:'Show Code',hide_code:'Hide Code',
    resume_dl:'Download Template',resume_preview:'Preview',resume_edit:'Edit',resume_updated:'> ✅ Resume updated. Check the editor or switch to Preview.',resume_analyze:'AI Analyze',resume_gen:'Generate Questions',resume_save:'Save',
    resume_saved:'Saved!',resume_analyzing:'Analyzing...',resume_ph:'Paste resume content (Markdown)...\n\nDownload LapisCV template, fill in, paste here, click Preview.',
    resume_empty:'Paste your resume on the left, then click "AI Analyze"',resume_chat_ph:'Ask AI for resume improvement...',
    interview_empty:'Paste resume in "Resume" tab, then click "Generate Questions"',
    interview_start:'Start Interview',interview_starting:'Starting...',interview_status_idle:'Not Started',
    interview_status_active:'In Progress',interview_ans_ph:'Type your answer...',
    interview_gen_ing:'Generating...',interview_confirm_reset:'Reset mock interview?',
    chat_welcome:'Hi! I\'m the BrushUp AI assistant. I can help you:<br>- Check study progress<br>- Recommend problems to solve<br>- Analyze weak areas<br>- Create study plans<br>- Answer algorithm questions<br><br>What would you like to know?',
    chat_ph:'Type a question...',btn_send:'Send',btn_clear:'Clear',
    confirm_clear:'Clear all chat history?',confirm_clear_resume:'Clear resume chat history?',
    chat_cleared:'Chat cleared. What would you like to ask?',thinking:'Thinking...',net_error:'Network error',
    analysis_fail:'Analysis failed',paste_first:'Please paste your resume first',
    data_updated:'Data: __TODAY__',
    nav_settings:'Settings',settings_list:'Problem List',settings_list_warn:'Switching list creates a new progress table. Existing data is preserved.',
    settings_rounds:'Review Rounds',settings_intervals:'Review Intervals (days)',
    settings_daily_new:'Daily New Suggestion',settings_daily_review:'Daily Review Suggestion',
    settings_deadline:'Deadline',settings_deadline_hint:'Empty = no limit',
    settings_save:'Save Settings',settings_saved:'Saved! Restart web server to apply',
    settings_daily_pace:'Suggested Daily Pace',settings_remaining:'Remaining',settings_days_left:'Days Left',
    theme_dark:'Dark',theme_light:'Light',
    nav_achievements:'Achievements',
    export_csv:'Export CSV',
    focus_mode:'Focus Mode',focus_select:'Select weak category',
    notes_ph:'Add notes...',notes_save:'Save Note',
    achievement_streak7:'7-day streak',achievement_streak30:'30-day streak',
    achievement_r1_all:'R1 all done',achievement_r1_half:'R1 half done',
    shortcut_hint:'Shortcuts: 1-9 to switch tabs',
  }
};
// Clean up old keys from previous project names
['leetforge_lang','offerpilot_lang'].forEach(function(k){localStorage.removeItem(k)});
var currentLang=localStorage.getItem('brushup_lang')||'en';

function t(key){return (I18N[currentLang]||I18N.en)[key]||(I18N.en[key]||key);}

function applyLang(){
  document.querySelectorAll('[data-i18n]').forEach(function(el){
    var key=el.getAttribute('data-i18n');
    var val=t(key);
    if(el.tagName==='INPUT'||el.tagName==='TEXTAREA') el.placeholder=val;
    else if(key==='chat_welcome'||key==='data_updated') el.innerHTML=val;
    else el.textContent=val;
  });
  document.getElementById('lang-en').className='lang-btn'+(currentLang==='en'?' active':'');
  document.getElementById('lang-zh').className='lang-btn'+(currentLang==='zh'?' active':'');
}

function switchLang(lang){
  currentLang=lang;
  localStorage.setItem('brushup_lang',lang);
  applyLang();
}

var currentTheme=localStorage.getItem('brushup_theme')||'dark';
function switchTheme(theme){
  currentTheme=theme;
  localStorage.setItem('brushup_theme',theme);
  document.body.className=theme==='light'?'light':'';
  document.getElementById('theme-dark').className='theme-btn'+(theme==='dark'?' active':'');
  document.getElementById('theme-light').className='theme-btn'+(theme==='light'?' active':'');
}
switchTheme(currentTheme);

const D = __DATA_JSON__;

// ====== User Profile ======
(function(){
  var p=D.user_profile;
  var profileEl=document.getElementById('user-profile');
  var loginBar=document.getElementById('user-login-bar');
  if(p&&p.username){
    document.getElementById('user-avatar').src=p.avatar||'';
    document.getElementById('user-name').textContent=p.username;
    profileEl.style.display='flex';
    if(!p.avatar) document.getElementById('user-avatar').style.display='none';
  } else {
    loginBar.style.display='flex';
  }
})();

// ====== Sync ======
(function(){
  var syncNav=document.getElementById('sync-btn-nav');
  var syncSep=document.getElementById('sync-sep');
  var syncText=document.getElementById('sync-btn-text');
  var p=D.user_profile;
  if(p&&p.username){
    syncNav.style.display='flex';
    syncSep.style.display='';
  }
  syncNav.addEventListener('click',function(){
    syncText.textContent='Syncing...';
    syncNav.style.pointerEvents='none';
    syncNav.style.opacity='0.5';
    fetch('/api/sync',{method:'POST'}).then(function(){
      // Poll for data change
      var oldRounds=D.done_rounds;
      var poll=setInterval(function(){
        fetch('/api/data').then(function(r){return r.json()}).then(function(nd){
          if(nd.done_rounds!==oldRounds||nd.total!==D.total){
            clearInterval(poll);
            location.reload();
          }
        }).catch(function(){});
      },3000);
      // Timeout: reload anyway after 30s
      setTimeout(function(){clearInterval(poll);syncText.textContent='Sync Now';syncNav.style.pointerEvents='';syncNav.style.opacity='1';location.reload();},30000);
    });
  });
})();

// ====== Logout / Login ======
document.getElementById('user-logout-btn').addEventListener('click',function(){
  if(!confirm('Log out and switch account?')) return;
  fetch('/api/logout',{method:'POST'}).then(function(){location.reload();});
});
document.getElementById('user-login-btn').addEventListener('click',function(){
  var btn=this;
  btn.disabled=true;
  btn.textContent='Opening browser...';
  fetch('/api/login',{method:'POST'}).then(function(){
    btn.textContent='Complete login in browser, then wait...';
    // Poll for login completion
    var poll=setInterval(function(){
      fetch('/api/data').then(function(r){return r.json()}).then(function(d){
        if(d.user_profile&&d.user_profile.username){
          clearInterval(poll);
          location.reload();
        }
      }).catch(function(){});
    },3000);
  });
});

// ====== Tab Navigation ======
function switchTab(tabName){
  document.querySelectorAll('.nav-item').forEach(function(n){n.classList.remove('active')});
  document.querySelectorAll('.tab-content').forEach(function(tc){tc.classList.remove('active')});
  var navEl=document.querySelector('[data-tab="'+tabName+'"]');
  if(navEl) navEl.classList.add('active');
  var tabEl=document.getElementById('tab-'+tabName);
  if(tabEl) tabEl.classList.add('active');
  location.hash=tabName;
}
document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', () => {
    switchTab(item.dataset.tab);
    // Resize charts when switching to dashboard
    if (item.dataset.tab === 'dashboard') {
      setTimeout(() => {
        ['gauge','rounds','radar','trend','heatmap'].forEach(id => {
          var c = echarts.getInstanceByDom(document.getElementById(id));
          if(c) c.resize();
        });
      }, 50);
    }
    if (item.dataset.tab === 'checkin') {
      setTimeout(() => {
        var c = echarts.getInstanceByDom(document.getElementById('checkin-trend'));
        if(c) c.resize();
      }, 50);
    }
  });
});

// Badge counts
if (D.review_due && D.review_due.length > 0) {
  var badge = document.createElement('span');
  badge.className = 'badge';
  badge.textContent = D.review_due.length;
  document.getElementById('nav-review').appendChild(badge);
}
if (D.optimizations && D.optimizations.length > 0) {
  var badge2 = document.createElement('span');
  badge2.className = 'badge';
  badge2.style.background = '#d29922';
  badge2.textContent = D.optimizations.length;
  document.getElementById('nav-optimize').appendChild(badge2);
}

// ====== Dashboard Charts ======
// Gauge
echarts.init(document.getElementById('gauge')).setOption({
  series: [{
    type:'gauge', startAngle:200, endAngle:-20, min:0, max:100,
    axisLine:{lineStyle:{width:20,color:[[0.2,'#007ec6'],[0.5,'#dfb317'],[0.8,'#97ca00'],[1,'#4c1']]}},
    pointer:{itemStyle:{color:'#58a6ff'}},
    axisTick:{show:false}, splitLine:{show:false},
    axisLabel:{color:'#8b949e',fontSize:12},
    detail:{valueAnimation:true,formatter:'{value}%',color:'#e6edf3',fontSize:28,offsetCenter:[0,'70%']},
    data:[{value:D.rate}]
  }]
});

// Rounds bar
echarts.init(document.getElementById('rounds')).setOption({
  tooltip:{trigger:'axis'},
  xAxis:{type:'category',data:['R1','R2','R3','R4','R5'],axisLabel:{color:'#8b949e'},axisLine:{lineStyle:{color:'#30363d'}}},
  yAxis:{type:'value',max:D.total,axisLabel:{color:'#8b949e'},splitLine:{lineStyle:{color:'#21262d'}}},
  series:[{
    type:'bar',data:D.per_round,barWidth:'50%',
    itemStyle:{borderRadius:[6,6,0,0],color:function(p){return['#4c1','#97ca00','#dfb317','#007ec6','#e34c26'][p.dataIndex]}},
    label:{show:true,position:'top',color:'#e6edf3'}
  }]
});

// Radar
var catNames=D.categories.map(c=>c[0]);
var catR1=D.categories.map(c=>c[1]);
echarts.init(document.getElementById('radar')).setOption({
  radar:{
    indicator:catNames.map(n=>({name:n,max:100})),
    axisName:{color:'#8b949e',fontSize:11},
    splitArea:{areaStyle:{color:['#161b22','#1a2030']}},
    axisLine:{lineStyle:{color:'#30363d'}},
    splitLine:{lineStyle:{color:'#30363d'}},
  },
  series:[{type:'radar',data:[{
    value:catR1,name:'R1 rate',
    areaStyle:{color:'rgba(88,166,255,0.25)'},
    lineStyle:{color:'#58a6ff'},itemStyle:{color:'#58a6ff'}
  }]}]
});

// Trend
if(D.daily.length>0){
  var dates=D.daily.map(d=>d[0]);
  var newC=D.daily.map(d=>d[1]);
  var revC=D.daily.map(d=>d[2]);
  echarts.init(document.getElementById('trend')).setOption({
    tooltip:{trigger:'axis'},
    legend:{data:[t('chart_new'),t('chart_review')],textStyle:{color:'#8b949e'}},
    xAxis:{type:'category',data:dates,axisLabel:{color:'#8b949e'},axisLine:{lineStyle:{color:'#30363d'}}},
    yAxis:{type:'value',axisLabel:{color:'#8b949e'},splitLine:{lineStyle:{color:'#21262d'}}},
    series:[
      {name:t('chart_new'),type:'bar',stack:'total',data:newC,itemStyle:{color:'#58a6ff'}},
      {name:t('chart_review'),type:'bar',stack:'total',data:revC,itemStyle:{color:'#3fb950'}}
    ]
  });
} else {
  document.getElementById('trend').innerHTML='<div class="empty-state"><p>'+t('empty')+'</p></div>';
}

// Heatmap — GitHub style
(function(){
  var el=document.getElementById('heatmap');
  var chart=echarts.init(el);
  var today=new Date();
  var start=new Date(today);start.setDate(start.getDate()-365);
  var isLight=document.body.classList.contains('light');
  var bgColor=isLight?'#ebedf0':'#161b22';
  var colors=isLight?['#ebedf0','#9be9a8','#40c463','#30a14e','#216e39']:['#2d333b','#0e4429','#006d32','#26a641','#39d353'];
  chart.setOption({
    tooltip:{
      formatter:function(p){
        if(!p.value) return '';
        var d=p.value[0],n=p.value[1]||0;
        return '<div style="font-size:12px;padding:2px 4px"><strong>'+d+'</strong><br/>'+n+' problem'+(n!==1?'s':'')+'</div>';
      },
      backgroundColor:isLight?'#fff':'#1c2129',
      borderColor:isLight?'#d0d7de':'#30363d',
      textStyle:{color:isLight?'#1f2328':'#e6edf3'},
    },
    visualMap:{
      min:0,max:6,show:true,orient:'horizontal',
      right:20,bottom:10,
      itemWidth:12,itemHeight:12,
      text:['More','Less'],
      textStyle:{color:'#8b949e',fontSize:10},
      inRange:{color:colors},
    },
    calendar:{
      range:[start.toISOString().slice(0,10),today.toISOString().slice(0,10)],
      cellSize:[14,14],
      itemStyle:{color:isLight?'#ebedf0':'#2d333b',borderWidth:3,borderColor:isLight?'#fff':'#161b22',borderRadius:2},
      splitLine:{show:false},
      dayLabel:{color:'#8b949e',nameMap:['','Mon','','Wed','','Fri',''],fontSize:10,margin:8},
      monthLabel:{color:'#8b949e',fontSize:11,margin:12},
      yearLabel:{show:false},
      top:30,left:50,right:40,
    },
    series:[{
      type:'heatmap',coordinateSystem:'calendar',data:D.heatmap_data,
      itemStyle:{borderRadius:2},
    }]
  });
})();

window.addEventListener('resize',function(){
  ['gauge','rounds','radar','trend','heatmap','checkin-trend'].forEach(function(id){
    var el=document.getElementById(id);
    if(el){var c=echarts.getInstanceByDom(el);if(c)c.resize();}
  });
});

// ====== Today's Plan ======
(function(){
  // New todos (R1 not done)
  var newList=document.getElementById('today-new');
  var newCount=document.getElementById('new-count');
  var todos=D.new_todo||[];
  newCount.textContent=todos.length;
  if(todos.length===0){
    newList.innerHTML='<li style="color:var(--dim)">'+t('r1_done')+'</li>';
  } else {
    var h='';
    todos.forEach(function(item){
      var dc=item.difficulty==='简单'?'diff-easy':item.difficulty==='困难'?'diff-hard':'diff-medium';
      h+='<li><a href="https://leetcode.cn/problems/'+item.slug+'/" target="_blank">'+item.title+'</a>'
        +'<div class="today-meta"><span class="tag tag-cat">'+item.category+'</span><span class="tag '+dc+'">'+item.difficulty+'</span></div></li>';
    });
    newList.innerHTML=h;
  }

  // Review due
  var revList=document.getElementById('today-review');
  var revCount=document.getElementById('review-count-dash');
  var reviews=D.review_due||[];
  revCount.textContent=reviews.length;
  if(reviews.length===0){
    revList.innerHTML='<li style="color:var(--green)">'+t('no_review')+'</li>';
  } else {
    var h='';
    reviews.forEach(function(r){
      var status=r.overdue>0?'<span class="tag tag-review">'+t('overdue').replace('{n}',r.overdue)+'</span>':'<span class="tag tag-new">'+t('due_today')+'</span>';
      h+='<li><span>'+r.title+'</span><div class="today-meta"><span class="tag tag-cat">'+r.round+'</span>'+status+'</div></li>';
    });
    revList.innerHTML=h;
  }
})();

// ====== Progress Table ======
var diffMap={'easy':'Easy','medium':'Medium','hard':'Hard'};
var allCategories=[...new Set(D.rows.map(r=>r.category))].sort();
var catSelect=document.getElementById('filter-category');
allCategories.forEach(c=>{var o=document.createElement('option');o.value=c;o.textContent=c;catSelect.appendChild(o);});

// renderTable defined later with notes support
document.getElementById('search-input').addEventListener('input',function(){renderTable()});
document.getElementById('filter-difficulty').addEventListener('change',function(){renderTable()});
document.getElementById('filter-category').addEventListener('change',function(){renderTable()});
document.getElementById('filter-status').addEventListener('change',function(){renderTable()});
document.getElementById('clear-filters').addEventListener('click',function(){
  document.getElementById('search-input').value='';
  document.getElementById('filter-difficulty').value='';
  document.getElementById('filter-category').value='';
  document.getElementById('filter-status').value='';
  renderTable();
});

// ====== Checkin Timeline ======
(function(){
  var container=document.getElementById('checkin-timeline');
  if(D.checkins.length===0){
    container.innerHTML='<div class="empty-state"><div class="icon">&#128197;</div><p>'+t('empty')+'</p></div>';
    document.getElementById('checkin-trend').innerHTML='<div class="empty-state"><p>'+t('empty')+'</p></div>';
    return;
  }
  var html='';
  D.checkins.forEach(function(c){
    html+='<div class="timeline-item'+(c.total===0?' empty':'')+'">'
      +'<div class="timeline-date">'+c.date+'</div>'
      +'<div class="timeline-stats">'
      +'<span class="timeline-new">'+t('chart_new')+' '+c.new+'</span>'
      +'<span class="timeline-review">'+t('chart_review')+' '+c.review+'</span>'
      +'<span class="timeline-total">Total '+c.total+'</span>'
      +'</div>'
      +'</div>';
  });
  container.innerHTML=html;

  // Checkin trend chart
  var dates=D.checkins.slice().reverse().slice(-30).map(c=>c.date.slice(5));
  var newC=D.checkins.slice().reverse().slice(-30).map(c=>c.new);
  var revC=D.checkins.slice().reverse().slice(-30).map(c=>c.review);
  echarts.init(document.getElementById('checkin-trend')).setOption({
    tooltip:{trigger:'axis'},
    legend:{data:[t('chart_new'),t('chart_review')],textStyle:{color:'#8b949e'}},
    xAxis:{type:'category',data:dates,axisLabel:{color:'#8b949e',rotate:45},axisLine:{lineStyle:{color:'#30363d'}}},
    yAxis:{type:'value',axisLabel:{color:'#8b949e'},splitLine:{lineStyle:{color:'#21262d'}}},
    series:[
      {name:t('chart_new'),type:'line',data:newC,smooth:true,itemStyle:{color:'#58a6ff'},areaStyle:{color:'rgba(88,166,255,0.1)'}},
      {name:t('chart_review'),type:'line',data:revC,smooth:true,itemStyle:{color:'#3fb950'},areaStyle:{color:'rgba(63,185,80,0.1)'}}
    ]
  });
})();

// ====== Review Due ======
(function(){
  var list=document.getElementById('review-list');
  var count=document.getElementById('review-count');
  if(!D.review_due||D.review_due.length===0){
    document.getElementById('review-card').innerHTML='<div class="empty-state"><div class="icon">&#9989;</div><p>'+t('no_review')+'</p></div>';
    count.textContent='(0)';
    return;
  }
  count.textContent='('+D.review_due.length+')';
  var html='';
  D.review_due.forEach(function(r){
    var status=r.overdue>0?'<span class="overdue">'+t('overdue').replace('{n}',r.overdue)+'</span>':'<span class="due-today">'+t('due_today')+'</span>';
    html+='<li><div><span class="review-round">'+r.round+'</span> '+r.title+'</div>'+status+'</li>';
  });
  list.innerHTML=html;
})();

// ====== Optimization ======
function mdToHtml(md){
  if(!md) return '';
  if(typeof marked!=='undefined'){
    marked.setOptions({breaks:true,gfm:true});
    return marked.parse(md);
  }
  // fallback: basic escaping
  return '<p>'+md.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>')+'</p>';
}
(function(){
  var container=document.getElementById('optimize-list');
  var count=document.getElementById('opt-count');
  if(!D.optimizations||D.optimizations.length===0){
    container.innerHTML='<div class="empty-state"><div class="icon">&#9889;</div><p>'+t('no_opt')+'</p></div>';
    count.textContent='(0)';
    return;
  }
  count.textContent='('+D.optimizations.length+')';
  var html='';
  D.optimizations.forEach(function(o,i){
    var rtPct=o.runtime_pct||0;
    var memPct=o.memory_pct||0;
    var rtClass=rtPct<30?'pct-low':rtPct<50?'pct-mid':'pct-high';
    var memClass=memPct<30?'pct-low':memPct<50?'pct-mid':'pct-high';
    var sugs='';
    if(o.suggestions){o.suggestions.forEach(function(s){sugs+='<li>'+s+'</li>';});}

    var aiHtml='';
    if(o.ai_analysis){
      aiHtml='<div class="ai-section">'
        +'<div class="ai-label">'+t('ai_analysis')+' <button class="ai-toggle" onclick="var b=document.getElementById(\'ai-'+i+'\');b.style.display=b.style.display===\'none\'?\'block\':\'none\';this.textContent=b.style.display===\'none\'?t(\'btn_expand\'):t(\'btn_collapse\');">'+t('btn_collapse')+'</button></div>'
        +'<div class="ai-content" id="ai-'+i+'">'+mdToHtml(o.ai_analysis)+'</div>'
        +'</div>';
    }

    html+='<div class="opt-card">'
      +'<div class="opt-header"><span class="opt-title">'+o.title+'</span><span class="opt-lang">'+(o.lang||'')+'</span></div>'
      +'<div class="opt-metrics">'
      +'<div class="opt-metric">'+t('runtime')+(o.runtime||'N/A')+' <div class="pct-bar"><div class="pct-fill '+rtClass+'" style="width:'+rtPct+'%"></div></div> '+rtPct.toFixed(1)+'%</div>'
      +'<div class="opt-metric">'+t('memory')+(o.memory||'N/A')+' <div class="pct-bar"><div class="pct-fill '+memClass+'" style="width:'+memPct+'%"></div></div> '+memPct.toFixed(1)+'%</div>'
      +'</div>'
      +(sugs?'<ul class="opt-suggestions">'+sugs+'</ul>':'')
      +aiHtml
      +(o.code?'<button class="code-toggle" onclick="var b=document.getElementById(\'code-'+i+'\');b.classList.toggle(\'show\');this.textContent=b.classList.contains(\'show\')?t(\'hide_code\'):t(\'show_code\');">'+t('show_code')+'</button><pre class="code-block" id="code-'+i+'">'+o.code.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</pre>':'')
      +'</div>';
  });
  container.innerHTML=html;
})();

// ====== Resume ======
(function(){
  var input=document.getElementById('resume-input');
  var analyzeBtn=document.getElementById('resume-analyze-btn');
  var saveBtn=document.getElementById('resume-save-btn');
  var previewToggle=document.getElementById('resume-preview-toggle');
  var previewContent=document.getElementById('resume-preview-content');
  var resumeLayout=document.querySelector('.resume-layout');
  var analysisDiv=document.getElementById('resume-analysis');
  var chatMsgs=document.getElementById('resume-chat-messages');
  var chatInput=document.getElementById('resume-chat-input');
  var resumeSelector=document.getElementById('resume-selector');
  var resumeNewBtn=document.getElementById('resume-new-btn');
  var resumeDelBtn=document.getElementById('resume-del-btn');

  function populateResumeSelector(rl){
    resumeSelector.innerHTML='';
    (rl.list||[]).forEach(function(r){
      var o=document.createElement('option');
      o.value=r.id;o.textContent=r.name;
      resumeSelector.appendChild(o);
    });
    resumeSelector.value=rl.current||'default';
  }

  resumeSelector.addEventListener('change',function(){
    fetch('/api/resume',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'switch_resume',resume_id:resumeSelector.value})
    }).then(function(){location.hash='resume';location.reload();});
  });

  resumeNewBtn.addEventListener('click',function(){
    var name=prompt('简历名称：');
    if(!name) return;
    fetch('/api/resume',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'create_resume',name:name})
    }).then(function(){location.hash='resume';location.reload();});
  });

  resumeDelBtn.addEventListener('click',function(){
    var id=resumeSelector.value;
    if(id==='default'){alert('默认简历不能删除');return;}
    if(!confirm('确定删除这份简历？')) return;
    fetch('/api/resume',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'delete_resume',resume_id:id})
    }).then(function(){location.hash='resume';location.reload();});
  });
  var chatSend=document.getElementById('resume-chat-send');
  var chatClear=document.getElementById('resume-chat-clear');
  var resumeHistory=[];

  // Load saved resume
  fetch('/api/resume').then(r=>r.json()).then(function(d){
    if(d.resume_list) populateResumeSelector(d.resume_list);
    if(d.content) input.value=d.content;
    if(d.analysis) analysisDiv.innerHTML=mdToHtml(d.analysis);
    if(d.chat_history&&d.chat_history.length>0){
      resumeHistory=d.chat_history;
      resumeHistory.forEach(function(m){appendResumeMsg(m.role,m.content);});
    }
  }).catch(function(){});

  function appendResumeMsg(role,text){
    var div=document.createElement('div');
    div.className='chat-msg '+role;
    var bubble=document.createElement('div');
    bubble.className='chat-bubble';
    bubble.innerHTML=role==='assistant'?mdToHtml(text):text.replace(/&/g,'&amp;').replace(/</g,'&lt;');
    div.appendChild(bubble);
    chatMsgs.appendChild(div);
    chatMsgs.scrollTop=chatMsgs.scrollHeight;
  }

  // Version history
  document.getElementById('resume-versions-btn').addEventListener('click',function(){
    fetch('/api/resume',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'list_versions'})
    }).then(r=>r.json()).then(function(d){
      var vs=d.versions||[];
      if(!vs.length){alert('No version history yet');return;}
      var msg=vs.map(function(v,i){return (i+1)+'. '+v.display+' - '+v.preview}).join('\n');
      var idx=prompt('Select version to restore (1-'+vs.length+'):\n\n'+msg);
      if(!idx) return;
      var v=vs[parseInt(idx)-1];
      if(!v) return;
      fetch('/api/resume',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action:'restore_version',file:v.file})
      }).then(r=>r.json()).then(function(d2){
        if(d2.content!==undefined){input.value=d2.content;if(resumeLayout.classList.contains('preview-mode')){previewContent.innerHTML=typeof marked!=='undefined'?marked.parse(d2.content):d2.content;}}
      });
    });
  });

  // Preview toggle
  previewToggle.addEventListener('click',function(){
    var isPreview=resumeLayout.classList.toggle('preview-mode');
    previewToggle.classList.toggle('active',isPreview);
    previewToggle.textContent=isPreview?t('resume_edit'):t('resume_preview');
    if(isPreview){
      var md=input.value||'';
      previewContent.innerHTML=typeof marked!=='undefined'?marked.parse(md):md.replace(/</g,'&lt;').replace(/\n/g,'<br>');
    }
  });

  // Auto-update preview on input
  input.addEventListener('input',function(){
    if(resumeLayout.classList.contains('preview-mode')){
      previewContent.innerHTML=typeof marked!=='undefined'?marked.parse(input.value||''):input.value;
    }
  });

  saveBtn.addEventListener('click',function(){
    fetch('/api/resume',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'save',content:input.value})
    }).then(r=>r.json()).then(function(){saveBtn.textContent=t('resume_saved');setTimeout(function(){saveBtn.textContent=t('resume_save');},1500);});
  });

  analyzeBtn.addEventListener('click',function(){
    var content=input.value.trim();
    if(!content){alert(t('paste_first'));return;}
    analyzeBtn.disabled=true;
    analyzeBtn.textContent=t('resume_analyzing');
    analysisDiv.innerHTML='<div class="resume-empty"><div class="chat-typing">'+t('resume_analyzing')+'</div></div>';
    fetch('/api/resume',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'analyze',content:content})
    }).then(r=>r.json()).then(function(d){
      analyzeBtn.disabled=false;
      analyzeBtn.textContent=t('resume_analyze');
      if(d.analysis) analysisDiv.innerHTML=mdToHtml(d.analysis);
      else analysisDiv.innerHTML='<div class="resume-empty"><p>'+(d.error||t('analysis_fail'))+'</p></div>';
    }).catch(function(){
      analyzeBtn.disabled=false;
      analyzeBtn.textContent=t('resume_analyze');
      analysisDiv.innerHTML='<div class="resume-empty"><p>'+t('net_error')+'</p></div>';
    });
  });

  function sendResumeChat(){
    var text=chatInput.value.trim();
    if(!text) return;
    chatInput.value='';
    appendResumeMsg('user',text);
    chatSend.disabled=true;
    var typing=document.createElement('div');
    typing.className='chat-msg assistant';
    typing.innerHTML='<div class="chat-bubble chat-typing">'+t('thinking')+'</div>';
    chatMsgs.appendChild(typing);
    chatMsgs.scrollTop=chatMsgs.scrollHeight;
    fetch('/api/resume',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'chat',message:text,history:resumeHistory,content:input.value})
    }).then(r=>r.json()).then(function(d){
      chatMsgs.removeChild(typing);
      chatSend.disabled=false;
      if(d.reply){
        // Check if AI returned a full resume update
        var resumeMatch=d.reply.match(/```resume\n([\s\S]*?)```/);
        var displayReply=d.reply;
        if(resumeMatch){
          var newResume=resumeMatch[1].trim();
          input.value=newResume;
          // Save immediately
          fetch('/api/resume',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({action:'save',content:newResume})});
          // Update preview if in preview mode
          if(resumeLayout.classList.contains('preview-mode')){
            previewContent.innerHTML=typeof marked!=='undefined'?marked.parse(newResume):newResume;
          }
          // Replace raw resume block with a clean notice in chat
          displayReply=d.reply.replace(/```resume\n[\s\S]*?```/,t('resume_updated'));
        }
        appendResumeMsg('assistant',displayReply);
        resumeHistory.push({role:'user',content:text});
        resumeHistory.push({role:'assistant',content:d.reply});
      } else {
        appendResumeMsg('assistant',d.error||'Failed');
      }
    }).catch(function(){chatMsgs.removeChild(typing);chatSend.disabled=false;appendResumeMsg('assistant',''+t('net_error')+'');});
  }
  chatSend.addEventListener('click',sendResumeChat);
  chatInput.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendResumeChat();}});
  chatClear.addEventListener('click',function(){
    if(!confirm(t('confirm_clear_resume'))) return;
    fetch('/api/resume',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'clear_chat'})
    }).then(function(){resumeHistory=[];chatMsgs.innerHTML='';});
  });
})();

// ====== Interview ======
(function(){
  var questionsDiv=document.getElementById('interview-questions');
  var chatMsgs=document.getElementById('interview-chat-messages');
  var chatInput=document.getElementById('interview-chat-input');
  var chatSend=document.getElementById('interview-chat-send');
  var chatClear=document.getElementById('interview-chat-clear');
  var startBtn=document.getElementById('interview-start-btn');
  var statusEl=document.getElementById('interview-status');
  var genBtn=document.getElementById('resume-gen-interview-btn');
  var interviewHistory=[];
  var interviewActive=false;

  // Load saved questions & chat
  fetch('/api/interview').then(r=>r.json()).then(function(d){
    if(d.questions) questionsDiv.innerHTML=mdToHtml(d.questions);
    if(d.chat_history&&d.chat_history.length>0){
      interviewHistory=d.chat_history;
      interviewHistory.forEach(function(m){appendInterviewMsg(m.role,m.content);});
      setActive(true);
    }
  }).catch(function(){});

  function appendInterviewMsg(role,text){
    var div=document.createElement('div');
    div.className='chat-msg '+(role==='user'?'user':'assistant');
    var bubble=document.createElement('div');
    bubble.className='chat-bubble';
    bubble.innerHTML=role==='user'?text.replace(/&/g,'&amp;').replace(/</g,'&lt;'):mdToHtml(text);
    div.appendChild(bubble);
    chatMsgs.appendChild(div);
    chatMsgs.scrollTop=chatMsgs.scrollHeight;
  }

  function setActive(on){
    interviewActive=on;
    chatInput.disabled=!on;
    chatSend.disabled=!on;
    if(on){
      statusEl.textContent=t('interview_status_active');
      statusEl.className='interview-status status-active';
      startBtn.style.display='none';
    } else {
      statusEl.textContent=t('interview_status_idle');
      statusEl.className='interview-status status-idle';
      startBtn.style.display='';
    }
  }

  // Generate questions button (on Resume page)
  genBtn.addEventListener('click',function(){
    var content=document.getElementById('resume-input').value.trim();
    if(!content){alert(t('paste_first'));return;}
    genBtn.disabled=true;
    genBtn.textContent=t('interview_gen_ing');
    fetch('/api/interview',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'generate',content:content})
    }).then(r=>r.json()).then(function(d){
      genBtn.disabled=false;genBtn.textContent=t('resume_gen');
      if(d.questions){
        questionsDiv.innerHTML=mdToHtml(d.questions);
        // Switch to interview tab
        document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
        document.querySelector('[data-tab="interview"]').classList.add('active');
        document.getElementById('tab-interview').classList.add('active');
      } else {
        alert(d.error||'生成失败');
      }
    }).catch(function(){genBtn.disabled=false;genBtn.textContent=t('resume_gen');});
  });

  // Start mock interview
  startBtn.addEventListener('click',function(){
    var resumeContent=document.getElementById('resume-input').value.trim();
    if(!resumeContent){alert('请先在简历优化页面粘贴简历内容');return;}
    startBtn.disabled=true;
    startBtn.textContent=t('interview_starting');
    fetch('/api/interview',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'start'})
    }).then(r=>r.json()).then(function(d){
      startBtn.disabled=false;startBtn.textContent=t('interview_start');
      if(d.reply){
        interviewHistory=[];
        chatMsgs.innerHTML='';
        appendInterviewMsg('assistant',d.reply);
        interviewHistory.push({role:'assistant',content:d.reply});
        setActive(true);
      }
    }).catch(function(){startBtn.disabled=false;startBtn.textContent=t('interview_start');});
  });

  // Send answer
  function sendAnswer(){
    var text=chatInput.value.trim();
    if(!text||!interviewActive) return;
    chatInput.value='';
    appendInterviewMsg('user',text);
    chatSend.disabled=true;
    var typing=document.createElement('div');
    typing.className='chat-msg assistant';
    typing.innerHTML='<div class="chat-bubble chat-typing">'+t('thinking')+'</div>';
    chatMsgs.appendChild(typing);
    chatMsgs.scrollTop=chatMsgs.scrollHeight;
    fetch('/api/interview',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'chat',message:text,history:interviewHistory})
    }).then(r=>r.json()).then(function(d){
      chatMsgs.removeChild(typing);
      chatSend.disabled=false;
      if(d.reply){
        appendInterviewMsg('assistant',d.reply);
        interviewHistory.push({role:'user',content:text});
        interviewHistory.push({role:'assistant',content:d.reply});
      } else {
        appendInterviewMsg('assistant',d.error||'请求失败');
      }
    }).catch(function(){chatMsgs.removeChild(typing);chatSend.disabled=false;});
  }
  chatSend.addEventListener('click',sendAnswer);
  chatInput.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendAnswer();}});

  // Reset
  chatClear.addEventListener('click',function(){
    if(!confirm(t('interview_confirm_reset'))) return;
    fetch('/api/interview',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'clear'})
    }).then(function(){
      interviewHistory=[];chatMsgs.innerHTML='';setActive(false);
    });
  });
})();

// ====== Interview Report ======
(function(){
  var reportBtn=document.getElementById('interview-report-btn');
  var reportArea=document.getElementById('interview-report-area');
  if(!reportBtn||!reportArea) return;
  // Load existing report
  fetch('/api/interview').then(r=>r.json()).then(function(d){
    if(d.report){reportArea.innerHTML=mdToHtml(d.report);reportArea.style.display='block';}
  }).catch(function(){});
  reportBtn.addEventListener('click',function(){
    reportBtn.disabled=true;reportBtn.textContent='Generating...';
    fetch('/api/interview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'report'})
    }).then(r=>r.json()).then(function(d){
      reportBtn.disabled=false;reportBtn.textContent='Report';
      if(d.report){reportArea.innerHTML=mdToHtml(d.report);reportArea.style.display='block';}
      else{alert(d.error||'Failed');}
    }).catch(function(){reportBtn.disabled=false;reportBtn.textContent='Report';});
  });
})();

// ====== AI Chat ======
(function(){
  var messages=document.getElementById('chat-messages');
  var input=document.getElementById('chat-input');
  var btn=document.getElementById('chat-send');
  var clearBtn=document.getElementById('chat-clear');
  var history=[];

  function appendMsg(role,text){
    var div=document.createElement('div');
    div.className='chat-msg '+role;
    var bubble=document.createElement('div');
    bubble.className='chat-bubble';
    if(role==='assistant'){
      bubble.innerHTML=mdToHtml(text);
    } else {
      bubble.textContent=text;
    }
    div.appendChild(bubble);
    messages.appendChild(div);
    messages.scrollTop=messages.scrollHeight;
  }

  // 加载历史对话
  fetch('/api/chat/history').then(r=>r.json()).then(function(data){
    if(data.history&&data.history.length>0){
      history=data.history;
      history.forEach(function(m){appendMsg(m.role,m.content);});
    }
  }).catch(function(){});

  function send(){
    var text=input.value.trim();
    if(!text) return;
    input.value='';
    appendMsg('user',text);
    btn.disabled=true;
    var typing=document.createElement('div');
    typing.className='chat-msg assistant';
    typing.innerHTML='<div class="chat-bubble chat-typing">'+t('thinking')+'</div>';
    messages.appendChild(typing);
    messages.scrollTop=messages.scrollHeight;

    fetch('/api/chat',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:text,history:history})
    }).then(r=>r.json()).then(function(data){
      messages.removeChild(typing);
      btn.disabled=false;
      if(data.reply){
        appendMsg('assistant',data.reply);
        history.push({role:'user',content:text});
        history.push({role:'assistant',content:data.reply});
      } else {
        appendMsg('assistant',data.error||'请求失败，请重试。');
      }
    }).catch(function(){
      messages.removeChild(typing);
      btn.disabled=false;
      appendMsg('assistant',''+t('net_error')+'，请重试。');
    });
  }

  clearBtn.addEventListener('click',function(){
    if(!confirm(t('confirm_clear'))) return;
    fetch('/api/chat/history',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'clear'})
    }).then(function(){
      history=[];
      messages.innerHTML='<div class="chat-msg assistant"><div class="chat-bubble">'+t('chat_cleared')+'</div></div>';
    });
  });

  btn.addEventListener('click',send);
  input.addEventListener('keydown',function(e){
    if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}
  });
})();

// ====== Settings ======
(function(){
  var cfg=D.plan_config||{rounds:5,intervals:[1,3,7,14],daily_new:5,daily_review:10,deadline:''};
  // Populate problem list selector
  var listSelect=document.getElementById('set-problem-list');
  var lists=D.available_lists||{};
  Object.keys(lists).forEach(function(k){
    var o=document.createElement('option');
    o.value=k;
    o.textContent=lists[k].name+' ('+lists[k].count+')';
    listSelect.appendChild(o);
  });
  listSelect.value=cfg.problem_list||'hot100';

  document.getElementById('set-rounds').value=cfg.rounds;
  document.getElementById('set-intervals').value=cfg.intervals.join(', ');
  document.getElementById('set-daily-new').value=cfg.daily_new;
  document.getElementById('set-daily-review').value=cfg.daily_review;
  document.getElementById('set-deadline').value=cfg.deadline||'';

  function updatePace(){
    var card=document.getElementById('pace-card');
    var r1Done=D.per_round[0]||0;
    var total=D.total;
    var r1Remaining=total-r1Done;
    var deadline=document.getElementById('set-deadline').value;
    var dailyNew=parseInt(document.getElementById('set-daily-new').value)||5;
    var html='<h3 data-i18n="settings_daily_pace">'+t('settings_daily_pace')+'</h3>';
    html+='<div class="pace-row"><span>R1 '+t('settings_remaining')+'</span><span>'+r1Remaining+' / '+total+'</span></div>';
    if(deadline){
      var today=new Date();
      var dl=new Date(deadline);
      var daysLeft=Math.max(1,Math.ceil((dl-today)/(1000*60*60*24)));
      var pace=Math.ceil(r1Remaining/daysLeft);
      html+='<div class="pace-row"><span>'+t('settings_days_left')+'</span><span>'+daysLeft+'</span></div>';
      html+='<div class="pace-row"><span style="color:var(--accent)">R1 '+t('settings_daily_new')+'</span><span style="color:var(--accent);font-weight:bold">'+pace+' / day</span></div>';
    } else {
      var daysNeeded=Math.ceil(r1Remaining/dailyNew);
      html+='<div class="pace-row"><span>'+t('settings_daily_new')+' = '+dailyNew+'</span><span>~'+daysNeeded+' days</span></div>';
    }
    card.innerHTML=html;
  }
  updatePace();
  document.getElementById('set-deadline').addEventListener('change',updatePace);
  document.getElementById('set-daily-new').addEventListener('change',updatePace);

  document.getElementById('settings-save-btn').addEventListener('click',function(){
    var intervals=document.getElementById('set-intervals').value.split(',').map(function(s){return parseInt(s.trim())}).filter(function(n){return !isNaN(n)&&n>0});
    var newCfg={
      problem_list:document.getElementById('set-problem-list').value||'hot100',
      rounds:parseInt(document.getElementById('set-rounds').value)||5,
      intervals:intervals,
      daily_new:parseInt(document.getElementById('set-daily-new').value)||5,
      daily_review:parseInt(document.getElementById('set-daily-review').value)||10,
      deadline:document.getElementById('set-deadline').value||''
    };
    fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(newCfg)
    }).then(r=>r.json()).then(function(d){
      if(d.ok){ location.hash='settings'; location.reload(); }
    });
  });
})();

// ====== Auto Refresh ======
(function(){
  var fingerprint=D.done_rounds+'|'+D.done_problems+'|'+(D.review_due?D.review_due.length:0)+'|'+(D.optimizations?D.optimizations.length:0)+'|'+(D.new_todo?D.new_todo.length:0);
  setInterval(function(){
    fetch('/api/data').then(r=>r.json()).then(function(nd){
      var nf=nd.done_rounds+'|'+nd.done_problems+'|'+(nd.review_due?nd.review_due.length:0)+'|'+(nd.optimizations?nd.optimizations.length:0)+'|'+(nd.new_todo?nd.new_todo.length:0);
      if(nf!==fingerprint){
        fingerprint=nf;
        location.reload();
      }
    }).catch(function(){});
  }, 30000);
})();

// ====== Trend Stats ======
(function(){
  var ts=D.trend_stats||{};
  var el=document.getElementById('trend-stats');
  if(!el) return;
  function card(label,val,sub){return '<div style="background:var(--bg2);padding:10px 16px;border-radius:8px;min-width:120px;"><div style="font-size:20px;font-weight:bold;color:var(--accent)">'+val+'</div><div style="font-size:11px;color:var(--dim)">'+label+'</div>'+(sub?'<div style="font-size:11px;color:'+(sub.indexOf('+')>=0?'var(--green)':'var(--dim)')+'">'+sub+'</div>':'')+'</div>';}
  var wc=ts.week_change>0?'+'+ts.week_change+'%':ts.week_change+'%';
  el.innerHTML=card('This Week',ts.this_week||0,wc)+card('Last Week',ts.last_week||0,'')+card('This Month',ts.this_month||0,'')+card('Last Month',ts.last_month||0,'')+card('Avg Daily',ts.avg_daily||0,'last 30 days');
})();

// ====== Review Calendar ======
(function(){
  var cal=document.getElementById('review-calendar');
  if(!cal||!D.review_due) return;
  // Group by due_date
  var byDate={};
  D.review_due.forEach(function(r){
    var dd=r.due_date||'';
    if(!dd) return;
    if(!byDate[dd]) byDate[dd]=[];
    byDate[dd].push(r);
  });
  // Show next 14 days
  var today=new Date();
  var html='';
  for(var i=0;i<14;i++){
    var d=new Date(today);d.setDate(d.getDate()+i);
    var ds=d.toISOString().slice(0,10);
    var count=0;
    // Count reviews due on or before this date that aren't done
    D.review_due.forEach(function(r){
      var dueD=r.due_date||ds;
      if(dueD<=ds) count++;
    });
    // Only count for day 0 (today = all overdue + today), future days = scheduled that day
    if(i>0){ count=(byDate[ds]||[]).length; }
    var bg=count===0?'var(--border)':count<=2?'var(--green)':count<=5?'var(--yellow)':'var(--red)';
    var label=ds.slice(5);
    var dayName=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][d.getDay()];
    html+='<div style="text-align:center;min-width:60px;padding:8px;background:var(--card);border:1px solid var(--border);border-radius:6px;">'
      +'<div style="font-size:10px;color:var(--dim)">'+dayName+'</div>'
      +'<div style="font-size:11px;margin:2px 0">'+label+'</div>'
      +'<div style="font-size:18px;font-weight:bold;color:'+bg+'">'+count+'</div>'
      +'</div>';
  }
  cal.innerHTML=html;
})();

// ====== CSV Export ======
document.getElementById('export-csv-btn').addEventListener('click',function(){
  var header='#,Title,Slug,Difficulty,Category,'+D.rows[0]? Object.keys(D.rows[0]).filter(function(k){return k.match(/^r\d+$/)}).map(function(k){return k.toUpperCase()}).join(','):'R1,R2,R3,R4,R5';
  header='#,Title,Slug,Difficulty,Category,Status';
  // Build proper header with round keys
  var rKeys=[];
  if(D.rows.length>0){
    Object.keys(D.rows[0]).forEach(function(k){if(k.match(/^r\d+$/))rKeys.push(k)});
    rKeys.sort();
  }
  var csv='#,Title,Slug,Difficulty,Category,'+rKeys.map(function(k){return k.toUpperCase()}).join(',')+',Status\n';
  D.rows.forEach(function(r){
    var rounds=rKeys.map(function(k){return '"'+(r[k]||'')+'"'}).join(',');
    csv+=r.num+',"'+r.title+'",'+r.slug+','+r.difficulty+','+r.category+','+rounds+','+(r.status||'')+'\n';
  });
  var blob=new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8'});
  var a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='brushup_progress_'+new Date().toISOString().slice(0,10)+'.csv';
  a.click();
});

// ====== Notes in Progress Table ======
function renderTable(){
  var search=document.getElementById('search-input').value.toLowerCase();
  var diffF=document.getElementById('filter-difficulty').value;
  var catF=document.getElementById('filter-category').value;
  var statusF=document.getElementById('filter-status').value;
  var hasFilter=search||diffF||catF||statusF;
  document.getElementById('clear-filters').style.display=hasFilter?'inline-block':'none';

  var filtered=D.rows.filter(function(r){
    if(search && r.title.toLowerCase().indexOf(search)===-1 && r.num.toString().indexOf(search)===-1) return false;
    if(diffF){
      var d=r.difficulty;
      if(diffF==='easy'&&d!=='简单') return false;
      if(diffF==='medium'&&d!=='中等') return false;
      if(diffF==='hard'&&d!=='困难') return false;
    }
    if(catF && r.category!==catF) return false;
    if(statusF){
      var hasR1=r.r1&&r.r1!=='—'&&r.r1.trim()!=='';
      var rKeys2=[];Object.keys(r).forEach(function(k){if(k.match(/^r\d+$/))rKeys2.push(k)});
      var allDone=rKeys2.every(function(k){return r[k]&&r[k]!=='—'&&r[k].trim()!==''});
      if(statusF==='not-started'&&hasR1) return false;
      if(statusF==='in-progress'&&(!hasR1||allDone)) return false;
      if(statusF==='completed'&&!allDone) return false;
    }
    return true;
  });

  document.getElementById('table-count').textContent=t('table_count')
    .replace('{problems_done}', D.started_problems||0)
    .replace('{problems_total}', D.total||0)
    .replace('{done}', D.done_rounds||0)
    .replace('{rounds}', D.total_rounds||0)
    .replace('{shown}', filtered.length)
    .replace('{total}', D.rows.length);
  var pd=D.problem_data||{};
  var html='';
  var rKeys3=[];
  if(D.rows.length>0){Object.keys(D.rows[0]).forEach(function(k){if(k.match(/^r\d+$/))rKeys3.push(k)});rKeys3.sort();}
  filtered.forEach(function(r,idx){
    var diffClass=r.difficulty==='简单'?'diff-easy':r.difficulty==='困难'?'diff-hard':'diff-medium';
    function rc(v){
      if(v&&v!=='—'&&v.trim()!=='') return '<td class="round-cell"><span class="round-done">'+v+'</span></td>';
      return '<td class="round-cell"><span class="round-empty">-</span></td>';
    }
    var statusClass=r.status==='已完成'?'status-done':'status-progress';
    var statusText=r.status||'-';
    var roundCells=rKeys3.map(function(k){return rc(r[k])}).join('');
    html+='<tr style="cursor:pointer" data-slug="'+r.slug+'">'
      +'<td>'+r.num+'</td>'
      +'<td><a href="https://leetcode.cn/problems/'+r.slug+'/" target="_blank" onclick="event.stopPropagation()">'+r.title+'</a></td>'
      +'<td class="'+diffClass+'">'+r.difficulty+'</td>'
      +'<td><span class="cat-tag">'+r.category+'</span></td>'
      +roundCells
      +'<td class="'+statusClass+'">'+statusText+'</td>'
      +'</tr>';
    // Note row
    var pdata=pd[r.slug]||{};
    var note=pdata.notes||'';
    var reviews=pdata.ai_reviews||[];
    var reviewHtml='';
    if(reviews.length>0){
      reviewHtml='<details class="note-ai-reviews"><summary>AI 分析历史 ('+reviews.length+')</summary>';
      reviews.forEach(function(rv){reviewHtml+='<div style="margin:6px 0;padding:6px;background:var(--bg);border-radius:4px"><strong>'+rv.round+' ('+rv.date+')</strong><br>'+rv.analysis+'</div>';});
      reviewHtml+='</details>';
    }
    html+='<tr class="note-row"><td colspan="'+(4+rKeys3.length+1)+'">'
      +'<textarea class="note-textarea" data-slug="'+r.slug+'" placeholder="'+t('notes_ph')+'">'+note.replace(/</g,'&lt;')+'</textarea>'
      +'<div class="note-actions"><button class="note-save-btn" onclick="saveNote(this)" data-i18n="notes_save">'+t('notes_save')+'</button></div>'
      +reviewHtml
      +'</td></tr>';
  });
  document.getElementById('progress-body').innerHTML=html;
  // Click to toggle notes
  document.querySelectorAll('#progress-body tr[data-slug]').forEach(function(tr){
    tr.addEventListener('click',function(){
      var noteRow=tr.nextElementSibling;
      if(noteRow) noteRow.classList.toggle('show');
    });
  });
};
function saveNote(btn){
  var textarea=btn.parentElement.previousElementSibling;
  var slug=textarea.getAttribute('data-slug');
  fetch('/api/problem',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:'save_note',slug:slug,note:textarea.value})
  }).then(function(){btn.textContent='✓';setTimeout(function(){btn.textContent=t('notes_save')},1000)});
}
renderTable();

// ====== Keyboard Shortcuts ======
document.addEventListener('keydown',function(e){
  if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'||e.target.tagName==='SELECT') return;
  var tabs=['dashboard','chat','progress','review','checkin','optimize','resume','interview','settings'];
  var num=parseInt(e.key);
  if(num>=1&&num<=tabs.length){ switchTab(tabs[num-1]); }
});

// ====== Apply Language + Restore Tab ======
applyLang();
if(location.hash){var ht=location.hash.slice(1);if(document.getElementById('tab-'+ht)) switchTab(ht);}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP 服务
# ---------------------------------------------------------------------------


def _reload_data() -> dict:
    """从文件重新读取所有数据，供 /api/data 实时返回最新状态。"""
    from .progress import (
        parse_progress_table, _compute_stats, _compute_streak,
        _get_review_due, _estimate_completion, _load_optimizations,
    )
    from .features import parse_checkin_data
    from .config import PROGRESS_FILE, CHECKIN_FILE

    _, rows = parse_progress_table(PROGRESS_FILE)
    stats = _compute_stats(rows)
    checkin_data = parse_checkin_data(CHECKIN_FILE)
    streak, total_days = _compute_streak(CHECKIN_FILE)
    review_due = _get_review_due(rows, date.today())
    est = _estimate_completion(stats, total_days)
    optimizations = _load_optimizations()
    return _build_comprehensive_data(
        rows, stats, checkin_data, streak,
        total_days, review_due, optimizations, est,
    )


def serve_web(
    rows: list,
    stats: dict,
    checkin_data: list,
    streak: int,
    total_days: int,
    review_due: list,
    optimizations: list,
    est: str,
    port: int = 8100,
):
    """启动本地 Web 看板服务。"""

    def _render_html() -> bytes:
        """每次请求时重新生成 HTML（配置变更后立即生效）。"""
        fresh = _reload_data()
        today_str = date.today().strftime("%Y-%m-%d")
        s = fresh
        streak_class = "fire" if s.get("streak", 0) >= 3 else ""
        html = _HTML_TEMPLATE
        html = html.replace("__DATA_JSON__", json.dumps(fresh, ensure_ascii=False))
        html = html.replace("__DONE_ROUNDS__", str(s["done_rounds"]))
        html = html.replace("__TOTAL_ROUNDS__", str(s["total_rounds"]))
        html = html.replace("__RATE__", f"{s['rate']:.1f}")
        html = html.replace("__TODAY_AC__", str(s.get("today_ac", 0)))
        html = html.replace("__DONE_ALL__", str(s["done_problems"]))
        html = html.replace("__TOTAL__", str(s["total"]))
        html = html.replace("__STREAK__", str(s["streak"]))
        html = html.replace("__STREAK_CLASS__", streak_class)
        html = html.replace("__TOTAL_DAYS__", str(s["total_days"]))
        html = html.replace("__EST__", str(s["est"]))
        html = html.replace("__TODAY__", today_str)
        return html.encode("utf-8")

    class Handler(SimpleHTTPRequestHandler):
        def _start_login(self):
            global _LOGIN_RUNNING
            from .leetcode_api import browser_login

            with _LOGIN_LOCK:
                if _LOGIN_RUNNING:
                    result = {"status": "running"}
                    body = json.dumps(result).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                _LOGIN_RUNNING = True

            result = {"status": "started"}

            def _do_login():
                global _LOGIN_RUNNING
                try:
                    browser_login()
                    # 登录成功后自动同步，避免用户手动刷新后仍是旧数据。
                    from .sync import sync
                    sync(interactive=False)
                except Exception as e:
                    print(f"Login failed: {e}")
                finally:
                    with _LOGIN_LOCK:
                        _LOGIN_RUNNING = False

            threading.Thread(target=_do_login, daemon=True).start()
            body = json.dumps(result).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _start_sync(self):
            result = {"status": "started"}

            def _do_sync():
                try:
                    from .sync import sync
                    sync(interactive=False)
                except Exception as e:
                    print(f"Sync failed: {e}")

            threading.Thread(target=_do_sync, daemon=True).start()
            body = json.dumps(result).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/chat/history":
                from .ai_analyzer import load_chat_history
                hist = load_chat_history()
                body = json.dumps({"history": hist}, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/resume/template":
                from .resume import RESUME_TEMPLATE
                body = RESUME_TEMPLATE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=resume_template.md")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/resume":
                from .resume import load_resume, load_analysis, load_resume_chat, get_resume_list
                result = {
                    "content": load_resume(),
                    "analysis": load_analysis().get("text", ""),
                    "chat_history": load_resume_chat(),
                    "resume_list": get_resume_list(),
                }
                body = json.dumps(result, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/interview":
                from .resume import load_interview_questions, load_interview_chat, load_interview_report
                result = {
                    "questions": load_interview_questions(),
                    "chat_history": load_interview_chat(),
                    "report": load_interview_report(),
                }
                body = json.dumps(result, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/logout":
                from .config import COOKIES_FILE, DATA_DIR
                if COOKIES_FILE.exists():
                    COOKIES_FILE.unlink()
                pf = DATA_DIR / "user_profile.json"
                if pf.exists():
                    pf.unlink()
                body = json.dumps({"ok": True}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            elif self.path == "/api/sync":
                self._start_sync()
                return
            elif self.path == "/api/login":
                self._start_login()
                return
            elif self.path == "/api/data":
                fresh = _reload_data()
                body = json.dumps(fresh, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                page = _render_html()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)

        def do_POST(self):
            if self.path == "/api/login":
                self._start_login()
            elif self.path == "/api/sync":
                self._start_sync()
            elif self.path == "/api/chat":
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                try:
                    req = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    req = {}

                msg = req.get("message", "")
                history = req.get("history", [])

                from .config import get_ai_config
                ai_config = get_ai_config()
                if not ai_config["enabled"]:
                    result = {"error": "AI 未配置，请在 ~/.leetcode_auto/.env 中设置 AI_PROVIDER 和 AI_API_KEY"}
                else:
                    from .ai_analyzer import (
                        build_chat_context, chat as ai_chat,
                        save_chat_history, get_last_ai_error,
                    )
                    system_prompt = build_chat_context()
                    reply = ai_chat(msg, history, system_prompt)
                    if reply:
                        history.append({"role": "user", "content": msg})
                        history.append({"role": "assistant", "content": reply})
                        save_chat_history(history)
                        result = {"reply": reply}
                    else:
                        result = {"error": get_last_ai_error() or "AI 请求失败，请重试"}

                body = json.dumps(result, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/chat/history":
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                try:
                    req = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    req = {}
                if req.get("action") == "clear":
                    from .ai_analyzer import clear_chat_history
                    clear_chat_history()
                    result = {"ok": True}
                else:
                    result = {"error": "unknown action"}
                body = json.dumps(result, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/problem":
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                try:
                    req = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    req = {}
                action = req.get("action", "")
                from .problem_data import save_note, add_time_spent
                if action == "save_note":
                    save_note(req.get("slug", ""), req.get("note", ""))
                    result = {"ok": True}
                elif action == "add_time":
                    add_time_spent(req.get("slug", ""), req.get("seconds", 0))
                    result = {"ok": True}
                else:
                    result = {"error": "unknown"}
                body = json.dumps(result, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/settings":
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                try:
                    req = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    req = {}
                # 检查是否切换了题单
                old_cfg = load_plan_config()
                new_list = req.get("problem_list", "hot100")
                old_list = old_cfg.get("problem_list", "hot100")
                save_plan_config(req)
                if new_list != old_list:
                    # 切换题单：为新题单生成进度表（旧的保留备份）
                    from .problem_lists import get_problem_list
                    from .init_plan import _gen_progress_table
                    from .config import PROGRESS_FILE, PLAN_DIR
                    import shutil
                    backup = PLAN_DIR / f"01_进度表_{old_list}.md"
                    if PROGRESS_FILE.exists() and not backup.exists():
                        shutil.copy2(PROGRESS_FILE, backup)
                    # 检查新题单是否有备份
                    restore = PLAN_DIR / f"01_进度表_{new_list}.md"
                    if restore.exists():
                        shutil.copy2(restore, PROGRESS_FILE)
                    else:
                        problems = get_problem_list(new_list)
                        PROGRESS_FILE.write_text(
                            _gen_progress_table(problems), encoding="utf-8")
                body = json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/interview":
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                try:
                    req = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    req = {}
                action = req.get("action", "")
                from .resume import (
                    load_resume, generate_interview_questions,
                    chat_interview, save_interview_chat, clear_interview_chat,
                )
                from .ai_analyzer import get_last_ai_error
                if action == "generate":
                    content = req.get("content", "")
                    from .resume import save_resume as _sr
                    _sr(content)
                    questions = generate_interview_questions(content)
                    result = {"questions": questions} if questions else {"error": get_last_ai_error() or "AI 未配置或请求失败"}
                elif action == "start":
                    resume_content = load_resume()
                    if not resume_content:
                        result = {"error": "请先粘贴简历内容"}
                    else:
                        reply = chat_interview("请开始面试", [], resume_content)
                        if reply:
                            save_interview_chat([{"role": "assistant", "content": reply}])
                            result = {"reply": reply}
                        else:
                            result = {"error": get_last_ai_error() or "AI 未配置或请求失败"}
                elif action == "chat":
                    msg = req.get("message", "")
                    history = req.get("history", [])
                    resume_content = load_resume()
                    reply = chat_interview(msg, history, resume_content)
                    if reply:
                        history.append({"role": "user", "content": msg})
                        history.append({"role": "assistant", "content": reply})
                        save_interview_chat(history)
                        result = {"reply": reply}
                    else:
                        result = {"error": get_last_ai_error() or "AI 未配置或请求失败"}
                elif action == "clear":
                    clear_interview_chat()
                    result = {"ok": True}
                elif action == "report":
                    from .resume import generate_interview_report, load_interview_chat as _lic
                    hist = _lic()
                    report = generate_interview_report(hist)
                    result = {"report": report} if report else {"error": "AI 未配置或对话为空"}
                else:
                    result = {"error": "未知操作"}
                body = json.dumps(result, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/resume":
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                try:
                    req = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    req = {}

                action = req.get("action", "")
                from .resume import (
                    save_resume, load_resume, analyze_resume,
                    save_analysis, load_analysis,
                    chat_resume, save_resume_chat, clear_resume_chat,
                )
                from .ai_analyzer import get_last_ai_error

                if action == "save":
                    save_resume(req.get("content", ""))
                    result = {"ok": True}
                elif action == "analyze":
                    content = req.get("content", "")
                    save_resume(content)
                    analysis = analyze_resume(content)
                    if analysis:
                        save_analysis({"text": analysis})
                        result = {"analysis": analysis}
                    else:
                        result = {"error": get_last_ai_error() or "AI not configured or request failed"}
                elif action == "chat":
                    msg = req.get("message", "")
                    history = req.get("history", [])
                    # 优先用前端传来的最新内容
                    resume_content = req.get("content") or load_resume()
                    if req.get("content"):
                        save_resume(req["content"])
                    analysis_text = load_analysis().get("text", "")
                    reply = chat_resume(msg, history, resume_content, analysis_text)
                    if reply:
                        history.append({"role": "user", "content": msg})
                        history.append({"role": "assistant", "content": reply})
                        save_resume_chat(history)
                        result = {"reply": reply}
                    else:
                        result = {"error": get_last_ai_error() or "AI not configured or request failed"}
                elif action == "clear_chat":
                    clear_resume_chat()
                    result = {"ok": True}
                elif action == "switch_resume":
                    from .resume import switch_resume
                    switch_resume(req.get("resume_id", "default"))
                    result = {"ok": True}
                elif action == "create_resume":
                    from .resume import create_resume
                    new_id = create_resume(req.get("name", "新简历"))
                    result = {"ok": True, "id": new_id}
                elif action == "delete_resume":
                    from .resume import delete_resume
                    delete_resume(req.get("resume_id", ""))
                    result = {"ok": True}
                elif action == "rename_resume":
                    from .resume import rename_resume
                    rename_resume(req.get("resume_id", ""), req.get("name", ""))
                    result = {"ok": True}
                elif action == "list_versions":
                    from .resume import get_resume_versions
                    result = {"versions": get_resume_versions()}
                elif action == "restore_version":
                    from .resume import restore_resume_version
                    content = restore_resume_version(req.get("file", ""))
                    result = {"ok": True, "content": content}
                else:
                    result = {"error": "unknown action"}

                body = json.dumps(result, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"Web 看板已启动：{url}")
    print("按 Ctrl+C 停止\n")

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb 看板已停止。")
        server.server_close()
