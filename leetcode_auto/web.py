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
from .init_plan import SLUG_CATEGORY

# ---------------------------------------------------------------------------
# 数据构建
# ---------------------------------------------------------------------------


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

    # R1 未做的新题
    new_todo = []
    for row in rows:
        if row["r1"] and row["r1"] not in ("", "—"):
            continue
        title_match = re.search(r"\[(.+?)\]", row["title"])
        display_title = title_match.group(1) if title_match else row["title"]
        cat = SLUG_CATEGORY.get(row.get("title_slug", ""), "其他")
        new_todo.append({
            "title": display_title,
            "slug": row.get("title_slug", ""),
            "difficulty": row["difficulty"],
            "category": cat,
        })

    diff_order = {"简单": 0, "中等": 1, "困难": 2}
    new_todo.sort(key=lambda x: diff_order.get(x["difficulty"], 1))

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
        "total_rounds": stats["total_rounds"],
        "done_rounds": stats["done_rounds"],
        "done_problems": stats["done_problems"],
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
<style>
:root {
  --bg: #0d1117; --bg2: #161b22; --card: #1c2129; --border: #30363d;
  --text: #e6edf3; --dim: #8b949e; --accent: #58a6ff; --green: #3fb950;
  --yellow: #d29922; --red: #f85149; --orange: #f0883e;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; display:flex; min-height:100vh; }

/* Sidebar */
.sidebar { width:220px; background:var(--bg2); border-right:1px solid var(--border); padding:20px 0; position:fixed; height:100vh; overflow-y:auto; }
.sidebar h1 { font-size:16px; padding:0 20px 20px; border-bottom:1px solid var(--border); }
.sidebar h1 span { color:var(--accent); }
.nav-item { display:flex; align-items:center; gap:10px; padding:12px 20px; cursor:pointer; color:var(--dim); transition:all .2s; font-size:14px; border-left:3px solid transparent; }
.nav-item:hover { background:var(--card); color:var(--text); }
.nav-item.active { color:var(--accent); border-left-color:var(--accent); background:rgba(88,166,255,0.08); }
.nav-item .badge { background:var(--red); color:#fff; font-size:11px; padding:1px 6px; border-radius:10px; margin-left:auto; }

/* Main */
.main { margin-left:220px; flex:1; padding:24px; max-width:1400px; }
.tab-content { display:none; }
.tab-content.active { display:block; }

/* Stats */
.stats-row { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-bottom:20px; }
.stat-card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px; text-align:center; }
.stat-card .num { font-size:28px; font-weight:bold; color:var(--accent); }
.stat-card .label { font-size:12px; color:var(--dim); margin-top:4px; }
.stat-card .num.fire { color:var(--orange); }

/* Grid */
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(400px,1fr)); gap:16px; margin-bottom:16px; }
.card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px; }
.card h2 { font-size:14px; color:var(--dim); margin-bottom:12px; padding-bottom:8px; border-bottom:1px solid var(--border); }
.card-full { grid-column:1/-1; }
.chart { width:100%; height:320px; }
.chart-lg { width:100%; height:360px; }

/* Progress Table */
.table-controls { display:flex; gap:12px; margin-bottom:16px; flex-wrap:wrap; align-items:center; }
.table-controls input, .table-controls select {
  background:var(--bg2); border:1px solid var(--border); color:var(--text);
  padding:8px 12px; border-radius:6px; font-size:13px; outline:none;
}
.table-controls input:focus, .table-controls select:focus { border-color:var(--accent); }
.table-controls input { flex:1; min-width:200px; }
.table-controls select { min-width:120px; }
.progress-table { width:100%; border-collapse:collapse; font-size:13px; }
.progress-table th { text-align:left; padding:10px 8px; color:var(--dim); border-bottom:2px solid var(--border); position:sticky; top:0; background:var(--bg); font-weight:600; }
.progress-table td { padding:8px; border-bottom:1px solid var(--border); }
.progress-table tr:hover { background:rgba(88,166,255,0.04); }
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
.timeline-item { border-left:2px solid var(--border); padding:0 0 24px 20px; position:relative; margin-left:10px; }
.timeline-item::before { content:''; width:10px; height:10px; background:var(--accent); border-radius:50%; position:absolute; left:-6px; top:4px; }
.timeline-item.empty::before { background:var(--border); }
.timeline-date { font-weight:600; color:var(--accent); font-size:14px; }
.timeline-stats { display:flex; gap:16px; margin:8px 0; font-size:13px; }
.timeline-stats span { padding:2px 8px; border-radius:4px; }
.timeline-new { background:rgba(88,166,255,0.15); color:var(--accent); }
.timeline-review { background:rgba(63,185,80,0.15); color:var(--green); }
.timeline-total { background:rgba(139,148,158,0.15); color:var(--dim); }

/* Review Due */
.review-list { list-style:none; }
.review-list li { padding:10px 12px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; }
.review-list li:last-child { border:none; }
.review-round { font-size:12px; padding:2px 8px; border-radius:4px; background:rgba(88,166,255,0.15); color:var(--accent); }
.overdue { color:var(--red); font-size:12px; }
.due-today { color:var(--green); font-size:12px; }

/* Optimization */
.opt-card { background:var(--bg2); border:1px solid var(--border); border-radius:8px; padding:16px; margin-bottom:12px; }
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
.empty-state .icon { font-size:48px; margin-bottom:16px; }
.empty-state p { font-size:14px; }

/* Today Plan */
.today-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }
.today-card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px; }
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

/* Chat */
.chat-container { display:flex; flex-direction:column; height:calc(100vh - 120px); }
.chat-messages { flex:1; overflow-y:auto; padding:8px 0; }
.chat-msg { display:flex; margin-bottom:12px; }
.chat-msg.user { justify-content:flex-end; }
.chat-bubble { max-width:75%; padding:10px 14px; border-radius:12px; font-size:14px; line-height:1.6; white-space:pre-wrap; word-break:break-word; }
.chat-msg.user .chat-bubble { background:var(--accent); color:#fff; border-bottom-right-radius:4px; }
.chat-msg.assistant .chat-bubble { background:var(--card); border:1px solid var(--border); border-bottom-left-radius:4px; }
.chat-msg.assistant .chat-bubble h3 { font-size:14px; color:var(--accent); margin:8px 0 4px; }
.chat-msg.assistant .chat-bubble code { background:var(--bg); padding:1px 5px; border-radius:3px; font-size:12px; }
.chat-msg.assistant .chat-bubble pre { background:var(--bg); border:1px solid var(--border); border-radius:6px; padding:8px; margin:6px 0; font-size:12px; overflow-x:auto; }
.chat-msg.assistant .chat-bubble ul,.chat-msg.assistant .chat-bubble ol { margin-left:16px; }
.chat-input-row { display:flex; gap:8px; padding-top:12px; border-top:1px solid var(--border); }
.chat-input-row input { flex:1; background:var(--bg2); border:1px solid var(--border); color:var(--text); padding:10px 14px; border-radius:8px; font-size:14px; outline:none; }
.chat-input-row input:focus { border-color:var(--accent); }
.chat-input-row button { background:var(--accent); color:#fff; border:none; padding:10px 20px; border-radius:8px; font-size:14px; cursor:pointer; }
.chat-input-row button:hover { opacity:0.9; }
.chat-input-row button:disabled { opacity:0.5; cursor:not-allowed; }
.chat-typing { color:var(--dim); font-style:italic; font-size:13px; }

/* Responsive */
@media (max-width:768px) {
  .sidebar { display:none; }
  .main { margin-left:0; }
  .grid { grid-template-columns:1fr; }
  .stats-row { grid-template-columns:repeat(2,1fr); }
}

/* Page title */
.page-title { font-size:20px; font-weight:600; margin-bottom:20px; display:flex; align-items:center; gap:10px; }
.page-title .icon { font-size:24px; }
</style>
</head>
<body>

<nav class="sidebar">
  <h1><span>LeetCode</span> Hot100</h1>
  <div class="nav-item active" data-tab="dashboard">
    <span>Dashboard</span>
  </div>
  <div class="nav-item" data-tab="progress">
    <span>Progress</span>
  </div>
  <div class="nav-item" data-tab="checkin">
    <span>Checkin</span>
  </div>
  <div class="nav-item" data-tab="review" id="nav-review">
    <span>Review</span>
  </div>
  <div class="nav-item" data-tab="optimize" id="nav-optimize">
    <span>Optimize</span>
  </div>
  <div class="nav-item" data-tab="chat">
    <span>AI Chat</span>
  </div>
</nav>

<div class="main">

<!-- ==================== Dashboard ==================== -->
<div class="tab-content active" id="tab-dashboard">
  <div class="page-title"><span class="icon">&#127919;</span> Dashboard</div>
  <div class="stats-row">
    <div class="stat-card"><div class="num">__DONE_ROUNDS__</div><div class="label">done / __TOTAL_ROUNDS__ rounds</div></div>
    <div class="stat-card"><div class="num">__RATE__%</div><div class="label">rate</div></div>
    <div class="stat-card"><div class="num">__DONE_ALL__</div><div class="label">pass / __TOTAL__ problems</div></div>
    <div class="stat-card"><div class="num __STREAK_CLASS__">__STREAK__</div><div class="label">streak (days)</div></div>
    <div class="stat-card"><div class="num">__TOTAL_DAYS__</div><div class="label">total days</div></div>
    <div class="stat-card"><div class="label" style="font-size:13px;margin-top:8px;">__EST__</div><div class="label">estimated</div></div>
  </div>
  <div class="today-grid">
    <div class="today-card">
      <h2>Today: New <span class="count count-accent" id="new-count"></span></h2>
      <ul class="today-list" id="today-new"></ul>
    </div>
    <div class="today-card">
      <h2>Today: Review <span class="count count-red" id="review-count-dash"></span></h2>
      <ul class="today-list" id="today-review"></ul>
    </div>
  </div>
  <div class="grid">
    <div class="card"><h2>Rate</h2><div id="gauge" class="chart"></div></div>
    <div class="card"><h2>Round Progress</h2><div id="rounds" class="chart"></div></div>
    <div class="card"><h2>Category</h2><div id="radar" class="chart"></div></div>
    <div class="card"><h2>Daily Trend</h2><div id="trend" class="chart"></div></div>
    <div class="card card-full"><h2>Heatmap</h2><div id="heatmap" class="chart-lg"></div></div>
  </div>
</div>

<!-- ==================== Progress ==================== -->
<div class="tab-content" id="tab-progress">
  <div class="page-title"><span class="icon">&#128202;</span> Progress <span class="table-count" id="table-count"></span></div>
  <div class="table-controls">
    <input type="text" id="search-input" placeholder="Search...">
    <select id="filter-difficulty">
      <option value="">All</option>
      <option value="easy">Easy</option>
      <option value="medium">Medium</option>
      <option value="hard">Hard</option>
    </select>
    <select id="filter-category"><option value="">All</option></select>
    <select id="filter-status">
      <option value="">All</option>
      <option value="not-started">Not Started</option>
      <option value="in-progress">In Progress</option>
      <option value="completed">Completed</option>
    </select>
  </div>
  <div class="table-wrapper">
    <table class="progress-table">
      <thead>
        <tr>
          <th>#</th><th>Title</th><th>Difficulty</th><th>Category</th>
          <th class="round-cell">R1</th><th class="round-cell">R2</th>
          <th class="round-cell">R3</th><th class="round-cell">R4</th>
          <th class="round-cell">R5</th><th>Status</th>
        </tr>
      </thead>
      <tbody id="progress-body"></tbody>
    </table>
  </div>
</div>

<!-- ==================== Checkin ==================== -->
<div class="tab-content" id="tab-checkin">
  <div class="page-title"><span class="icon">&#128197;</span> Check-in History</div>
  <div class="grid">
    <div class="card card-full"><h2>Daily Trend</h2><div id="checkin-trend" class="chart"></div></div>
  </div>
  <div class="timeline" id="checkin-timeline"></div>
</div>

<!-- ==================== Review ==================== -->
<div class="tab-content" id="tab-review">
  <div class="page-title"><span class="icon">&#128214;</span> Review Due <span class="table-count" id="review-count"></span></div>
  <div class="card" id="review-card">
    <ul class="review-list" id="review-list"></ul>
  </div>
</div>

<!-- ==================== Optimize ==================== -->
<div class="tab-content" id="tab-optimize">
  <div class="page-title"><span class="icon">&#9889;</span> Optimization <span class="table-count" id="opt-count"></span></div>
  <div id="optimize-list"></div>
</div>

<!-- ==================== AI Chat ==================== -->
<div class="tab-content" id="tab-chat">
  <div class="page-title"><span class="icon">&#128172;</span> AI Chat</div>
  <div class="chat-container">
    <div class="chat-messages" id="chat-messages">
      <div class="chat-msg assistant"><div class="chat-bubble">你好！我是 LeetForge AI 助手，可以帮你：<br>- 查看刷题进度和统计<br>- 推荐今天该刷的题<br>- 分析薄弱环节<br>- 制定学习计划<br>- 解答算法问题<br><br>有什么想问的？</div></div>
    </div>
    <div class="chat-input-row">
      <input type="text" id="chat-input" placeholder="输入问题..." autocomplete="off">
      <button id="chat-send">发送</button>
    </div>
  </div>
</div>

</div><!-- /main -->

<script>
const D = __DATA_JSON__;

// ====== Tab Navigation ======
document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    item.classList.add('active');
    document.getElementById('tab-' + item.dataset.tab).classList.add('active');
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
    legend:{data:['New','Review'],textStyle:{color:'#8b949e'}},
    xAxis:{type:'category',data:dates,axisLabel:{color:'#8b949e'},axisLine:{lineStyle:{color:'#30363d'}}},
    yAxis:{type:'value',axisLabel:{color:'#8b949e'},splitLine:{lineStyle:{color:'#21262d'}}},
    series:[
      {name:'New',type:'bar',stack:'total',data:newC,itemStyle:{color:'#58a6ff'}},
      {name:'Review',type:'bar',stack:'total',data:revC,itemStyle:{color:'#3fb950'}}
    ]
  });
} else {
  document.getElementById('trend').innerHTML='<div class="empty-state"><p>No Data</p></div>';
}

// Heatmap
(function(){
  var chart=echarts.init(document.getElementById('heatmap'));
  var today=new Date();
  var start=new Date(today);start.setDate(start.getDate()-365);
  chart.setOption({
    tooltip:{formatter:function(p){return p.value[0]+': '+p.value[1]+' solved';}},
    visualMap:{min:0,max:8,show:false,inRange:{color:['#161b22','#0e4429','#006d32','#26a641','#39d353']}},
    calendar:{
      range:[start.toISOString().slice(0,10),today.toISOString().slice(0,10)],
      cellSize:[16,16],
      itemStyle:{borderWidth:3,borderColor:'#0d1117'},
      splitLine:{show:false},
      dayLabel:{color:'#8b949e',nameMap:'en',fontSize:10},
      monthLabel:{color:'#8b949e',fontSize:11},
      yearLabel:{show:false},
    },
    series:[{type:'heatmap',coordinateSystem:'calendar',data:D.heatmap_data}]
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
  var showNew=todos.slice(0,10);
  newCount.textContent=todos.length;
  if(showNew.length===0){
    newList.innerHTML='<li style="color:var(--dim)">R1 done!</li>';
  } else {
    var h='';
    showNew.forEach(function(t){
      var dc=t.difficulty==='简单'?'diff-easy':t.difficulty==='困难'?'diff-hard':'diff-medium';
      h+='<li><a href="https://leetcode.cn/problems/'+t.slug+'/" target="_blank">'+t.title+'</a>'
        +'<div class="today-meta"><span class="tag tag-cat">'+t.category+'</span><span class="tag '+dc+'">'+t.difficulty+'</span></div></li>';
    });
    if(todos.length>10) h+='<li style="color:var(--dim)">... '+todos.length+' problems remaining</li>';
    newList.innerHTML=h;
  }

  // Review due
  var revList=document.getElementById('today-review');
  var revCount=document.getElementById('review-count-dash');
  var reviews=D.review_due||[];
  revCount.textContent=reviews.length;
  if(reviews.length===0){
    revList.innerHTML='<li style="color:var(--green)">No reviews due today!</li>';
  } else {
    var h='';
    reviews.forEach(function(r){
      var status=r.overdue>0?'<span class="tag tag-review">overdue '+r.overdue+'d</span>':'<span class="tag tag-new">due today</span>';
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

function renderTable(){
  var search=document.getElementById('search-input').value.toLowerCase();
  var diffF=document.getElementById('filter-difficulty').value;
  var catF=document.getElementById('filter-category').value;
  var statusF=document.getElementById('filter-status').value;

  var filtered=D.rows.filter(function(r){
    if(search && r.title.toLowerCase().indexOf(search)===-1 && r.num.toString().indexOf(search)===-1) return false;
    if(diffF){
      var d=r.difficulty;
      if(diffF==='easy'&&d!=='easy'&&d!=='Easy'&&d!=='简单') return false;
      if(diffF==='medium'&&d!=='medium'&&d!=='Medium'&&d!=='中等') return false;
      if(diffF==='hard'&&d!=='hard'&&d!=='Hard'&&d!=='困难') return false;
    }
    if(catF && r.category!==catF) return false;
    if(statusF){
      var hasR1=r.r1&&r.r1!=='—'&&r.r1.trim()!=='';
      var allDone=hasR1&&r.r2&&r.r2!=='—'&&r.r2.trim()!==''&&r.r3&&r.r3!=='—'&&r.r3.trim()!==''&&r.r4&&r.r4!=='—'&&r.r4.trim()!==''&&r.r5&&r.r5!=='—'&&r.r5.trim()!=='';
      if(statusF==='not-started'&&hasR1) return false;
      if(statusF==='in-progress'&&(!hasR1||allDone)) return false;
      if(statusF==='completed'&&!allDone) return false;
    }
    return true;
  });

  document.getElementById('table-count').textContent='('+filtered.length+'/'+D.rows.length+')';

  var html='';
  filtered.forEach(function(r){
    var diffClass=r.difficulty==='简单'?'diff-easy':r.difficulty==='困难'?'diff-hard':'diff-medium';
    function rc(v){
      if(v&&v!=='—'&&v.trim()!=='') return '<td class="round-cell"><span class="round-done">'+v+'</span></td>';
      return '<td class="round-cell"><span class="round-empty">-</span></td>';
    }
    var statusClass=r.status==='已完成'?'status-done':'status-progress';
    var statusText=r.status||'-';
    html+='<tr>'
      +'<td>'+r.num+'</td>'
      +'<td><a href="https://leetcode.cn/problems/'+r.slug+'/" target="_blank">'+r.title+'</a></td>'
      +'<td class="'+diffClass+'">'+r.difficulty+'</td>'
      +'<td><span class="cat-tag">'+r.category+'</span></td>'
      +rc(r.r1)+rc(r.r2)+rc(r.r3)+rc(r.r4)+rc(r.r5)
      +'<td class="'+statusClass+'">'+statusText+'</td>'
      +'</tr>';
  });
  document.getElementById('progress-body').innerHTML=html;
}

document.getElementById('search-input').addEventListener('input',renderTable);
document.getElementById('filter-difficulty').addEventListener('change',renderTable);
document.getElementById('filter-category').addEventListener('change',renderTable);
document.getElementById('filter-status').addEventListener('change',renderTable);
renderTable();

// ====== Checkin Timeline ======
(function(){
  var container=document.getElementById('checkin-timeline');
  if(D.checkins.length===0){
    container.innerHTML='<div class="empty-state"><div class="icon">&#128197;</div><p>No Data</p></div>';
    document.getElementById('checkin-trend').innerHTML='<div class="empty-state"><p>No Data</p></div>';
    return;
  }
  var html='';
  D.checkins.forEach(function(c){
    html+='<div class="timeline-item'+(c.total===0?' empty':'')+'">'
      +'<div class="timeline-date">'+c.date+'</div>'
      +'<div class="timeline-stats">'
      +'<span class="timeline-new">New '+c.new+'</span>'
      +'<span class="timeline-review">Review '+c.review+'</span>'
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
    legend:{data:['New','Review'],textStyle:{color:'#8b949e'}},
    xAxis:{type:'category',data:dates,axisLabel:{color:'#8b949e',rotate:45},axisLine:{lineStyle:{color:'#30363d'}}},
    yAxis:{type:'value',axisLabel:{color:'#8b949e'},splitLine:{lineStyle:{color:'#21262d'}}},
    series:[
      {name:'New',type:'line',data:newC,smooth:true,itemStyle:{color:'#58a6ff'},areaStyle:{color:'rgba(88,166,255,0.1)'}},
      {name:'Review',type:'line',data:revC,smooth:true,itemStyle:{color:'#3fb950'},areaStyle:{color:'rgba(63,185,80,0.1)'}}
    ]
  });
})();

// ====== Review Due ======
(function(){
  var list=document.getElementById('review-list');
  var count=document.getElementById('review-count');
  if(!D.review_due||D.review_due.length===0){
    document.getElementById('review-card').innerHTML='<div class="empty-state"><div class="icon">&#9989;</div><p>No reviews due. Keep it up!</p></div>';
    count.textContent='(0)';
    return;
  }
  count.textContent='('+D.review_due.length+')';
  var html='';
  D.review_due.forEach(function(r){
    var status=r.overdue>0?'<span class="overdue">overdue '+r.overdue+' day(s)</span>':'<span class="due-today">due today</span>';
    html+='<li><div><span class="review-round">'+r.round+'</span> '+r.title+'</div>'+status+'</li>';
  });
  list.innerHTML=html;
})();

// ====== Optimization ======
function mdToHtml(md){
  if(!md) return '';
  var s=md;
  // code blocks
  s=s.replace(/```(\w*)\n([\s\S]*?)```/g,function(_,lang,code){
    return '<pre><code>'+code.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</code></pre>';
  });
  // inline code
  s=s.replace(/`([^`]+)`/g,'<code>$1</code>');
  // headers
  s=s.replace(/^### (.+)$/gm,'<h3>$1</h3>');
  s=s.replace(/^## (.+)$/gm,'<h3>$1</h3>');
  // bold
  s=s.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
  // list items
  s=s.replace(/^- (.+)$/gm,'<li>$1</li>');
  s=s.replace(/^(\d+)\. (.+)$/gm,'<li>$2</li>');
  // paragraphs
  s=s.replace(/\n{2,}/g,'</p><p>');
  return '<p>'+s+'</p>';
}
(function(){
  var container=document.getElementById('optimize-list');
  var count=document.getElementById('opt-count');
  if(!D.optimizations||D.optimizations.length===0){
    container.innerHTML='<div class="empty-state"><div class="icon">&#9889;</div><p>All submissions are well optimized!</p></div>';
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
        +'<div class="ai-label">AI Analysis <button class="ai-toggle" onclick="var b=document.getElementById(\'ai-'+i+'\');b.style.display=b.style.display===\'none\'?\'block\':\'none\';this.textContent=b.style.display===\'none\'?\'Show\':\'Hide\';">Hide</button></div>'
        +'<div class="ai-content" id="ai-'+i+'">'+mdToHtml(o.ai_analysis)+'</div>'
        +'</div>';
    }

    html+='<div class="opt-card">'
      +'<div class="opt-header"><span class="opt-title">'+o.title+'</span><span class="opt-lang">'+(o.lang||'')+'</span></div>'
      +'<div class="opt-metrics">'
      +'<div class="opt-metric">Runtime: '+(o.runtime||'N/A')+' <div class="pct-bar"><div class="pct-fill '+rtClass+'" style="width:'+rtPct+'%"></div></div> '+rtPct.toFixed(1)+'%</div>'
      +'<div class="opt-metric">Memory: '+(o.memory||'N/A')+' <div class="pct-bar"><div class="pct-fill '+memClass+'" style="width:'+memPct+'%"></div></div> '+memPct.toFixed(1)+'%</div>'
      +'</div>'
      +(sugs?'<ul class="opt-suggestions">'+sugs+'</ul>':'')
      +aiHtml
      +(o.code?'<button class="code-toggle" onclick="var b=document.getElementById(\'code-'+i+'\');b.classList.toggle(\'show\');this.textContent=b.classList.contains(\'show\')?\'Hide Code\':\'Show Code\';">Show Code</button><pre class="code-block" id="code-'+i+'">'+o.code.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</pre>':'')
      +'</div>';
  });
  container.innerHTML=html;
})();

// ====== AI Chat ======
(function(){
  var messages=document.getElementById('chat-messages');
  var input=document.getElementById('chat-input');
  var btn=document.getElementById('chat-send');
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

  function send(){
    var text=input.value.trim();
    if(!text) return;
    input.value='';
    appendMsg('user',text);
    btn.disabled=true;
    // typing indicator
    var typing=document.createElement('div');
    typing.className='chat-msg assistant';
    typing.innerHTML='<div class="chat-bubble chat-typing">thinking...</div>';
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
      appendMsg('assistant','网络错误，请重试。');
    });
  }

  btn.addEventListener('click',send);
  input.addEventListener('keydown',function(e){
    if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}
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
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP 服务
# ---------------------------------------------------------------------------


def _reload_data() -> dict:
    """从文件重新读取所有数据，供 /api/data 实时返回最新状态。"""
    from .sync import (
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
    data = _build_comprehensive_data(
        rows, stats, checkin_data, streak,
        total_days, review_due, optimizations, est,
    )
    today_str = date.today().strftime("%Y-%m-%d")
    streak_class = "fire" if streak >= 3 else ""

    html = _HTML_TEMPLATE
    html = html.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    html = html.replace("__DONE_ROUNDS__", str(stats["done_rounds"]))
    html = html.replace("__TOTAL_ROUNDS__", str(stats["total_rounds"]))
    html = html.replace("__RATE__", f"{stats['rate']:.1f}")
    html = html.replace("__DONE_ALL__", str(stats["done_problems"]))
    html = html.replace("__TOTAL__", str(stats["total"]))
    html = html.replace("__STREAK__", str(streak))
    html = html.replace("__STREAK_CLASS__", streak_class)
    html = html.replace("__TOTAL_DAYS__", str(total_days))
    html = html.replace("__EST__", est)
    html = html.replace("__TODAY__", today_str)

    html_bytes = html.encode("utf-8")

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/data":
                fresh = _reload_data()
                body = json.dumps(fresh, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.end_headers()
                self.wfile.write(html_bytes)

        def do_POST(self):
            if self.path == "/api/chat":
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
                    from .ai_analyzer import build_chat_context, chat as ai_chat
                    system_prompt = build_chat_context()
                    reply = ai_chat(msg, history, system_prompt)
                    if reply:
                        result = {"reply": reply}
                    else:
                        result = {"error": "AI 请求失败，请重试"}

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
