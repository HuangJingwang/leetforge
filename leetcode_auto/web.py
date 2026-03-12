"""本地 Web 看板：启动 HTTP 服务，展示 ECharts 交互式图表。"""

import json
import threading
import webbrowser
from datetime import date
from http.server import HTTPServer, SimpleHTTPRequestHandler

from .features import ROUND_KEYS, compute_category_stats

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeetCode Hot100 看板</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  :root { --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #e6edf3; --dim: #8b949e; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 20px; }
  h1 { text-align: center; font-size: 24px; margin-bottom: 24px; }
  h1 span { color: #58a6ff; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 16px; max-width: 1400px; margin: 0 auto; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
  .card h2 { font-size: 15px; color: var(--dim); margin-bottom: 12px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
  .chart { width: 100%; height: 320px; }
  .chart-lg { width: 100%; height: 380px; }
  .stats-row { display: flex; justify-content: space-around; text-align: center; margin-bottom: 16px; }
  .stat-item .num { font-size: 32px; font-weight: bold; color: #58a6ff; }
  .stat-item .label { font-size: 12px; color: var(--dim); }
  .streak-fire { color: #f0883e; }
  .footer { text-align: center; color: var(--dim); font-size: 12px; margin-top: 24px; }
</style>
</head>
<body>
<h1>🎯 <span>LeetCode Hot100</span> 刷题看板</h1>

<div class="stats-row">
  <div class="stat-item"><div class="num">__DONE_ROUNDS__</div><div class="label">已完成轮次 / __TOTAL_ROUNDS__</div></div>
  <div class="stat-item"><div class="num">__RATE__%</div><div class="label">完成率</div></div>
  <div class="stat-item"><div class="num">__DONE_ALL__</div><div class="label">5轮全通 / __TOTAL__</div></div>
  <div class="stat-item"><div class="num __STREAK_CLASS__">__STREAK__</div><div class="label">连续打卡 (天)</div></div>
</div>

<div class="grid">
  <div class="card"><h2>完成率仪表盘</h2><div id="gauge" class="chart"></div></div>
  <div class="card"><h2>各轮进度</h2><div id="rounds" class="chart"></div></div>
  <div class="card"><h2>分类能力雷达</h2><div id="radar" class="chart"></div></div>
  <div class="card"><h2>每日刷题趋势</h2><div id="trend" class="chart"></div></div>
  <div class="card" style="grid-column: 1 / -1"><h2>刷题热力图</h2><div id="heatmap" class="chart-lg"></div></div>
</div>

<div class="footer">由 <code>leetcode --web</code> 生成 · 数据截至 __TODAY__</div>

<script>
const D = __DATA_JSON__;

// Gauge
echarts.init(document.getElementById('gauge')).setOption({
  series: [{
    type: 'gauge', startAngle: 200, endAngle: -20,
    min: 0, max: 100,
    axisLine: { lineStyle: { width: 20, color: [[0.2,'#007ec6'],[0.5,'#dfb317'],[0.8,'#97ca00'],[1,'#4c1']] }},
    pointer: { itemStyle: { color: '#58a6ff' }},
    axisTick: { show: false }, splitLine: { show: false },
    axisLabel: { color: '#8b949e', fontSize: 12 },
    detail: { valueAnimation: true, formatter: '{value}%', color: '#e6edf3', fontSize: 28, offsetCenter: [0, '70%'] },
    data: [{ value: D.rate }]
  }]
});

// Rounds bar
echarts.init(document.getElementById('rounds')).setOption({
  tooltip: { trigger: 'axis' },
  xAxis: { type: 'category', data: ['R1','R2','R3','R4','R5'], axisLabel: { color: '#8b949e' }, axisLine: { lineStyle: { color: '#30363d' }}},
  yAxis: { type: 'value', max: D.total, axisLabel: { color: '#8b949e' }, splitLine: { lineStyle: { color: '#21262d' }}},
  series: [{
    type: 'bar', data: D.per_round, barWidth: '50%',
    itemStyle: { borderRadius: [6,6,0,0],
      color: function(p){ return ['#4c1','#97ca00','#dfb317','#007ec6','#e34c26'][p.dataIndex]; }
    },
    label: { show: true, position: 'top', color: '#e6edf3' }
  }]
});

// Radar
var catNames = D.categories.map(c=>c[0]);
var catR1 = D.categories.map(c=>c[1]);
echarts.init(document.getElementById('radar')).setOption({
  radar: {
    indicator: catNames.map(n=>({name:n, max:100})),
    axisName: { color: '#8b949e', fontSize: 11 },
    splitArea: { areaStyle: { color: ['#161b22','#1a2030'] }},
    axisLine: { lineStyle: { color: '#30363d' }},
    splitLine: { lineStyle: { color: '#30363d' }},
  },
  series: [{ type: 'radar', data: [{
    value: catR1,
    name: 'R1完成率',
    areaStyle: { color: 'rgba(88,166,255,0.25)' },
    lineStyle: { color: '#58a6ff' },
    itemStyle: { color: '#58a6ff' }
  }]}]
});

// Trend
if (D.daily.length > 0) {
  var dates = D.daily.map(d=>d[0]);
  var newC = D.daily.map(d=>d[1]);
  var revC = D.daily.map(d=>d[2]);
  echarts.init(document.getElementById('trend')).setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['新题','复习'], textStyle: { color: '#8b949e' }},
    xAxis: { type: 'category', data: dates, axisLabel: { color: '#8b949e' }, axisLine: { lineStyle: { color: '#30363d' }}},
    yAxis: { type: 'value', axisLabel: { color: '#8b949e' }, splitLine: { lineStyle: { color: '#21262d' }}},
    series: [
      { name: '新题', type: 'bar', stack: 'total', data: newC, itemStyle: { color: '#58a6ff' }},
      { name: '复习', type: 'bar', stack: 'total', data: revC, itemStyle: { color: '#3fb950' }}
    ]
  });
} else {
  document.getElementById('trend').innerHTML = '<div style="text-align:center;color:#8b949e;padding-top:120px;">暂无打卡数据</div>';
}

// Heatmap
(function(){
  var el = document.getElementById('heatmap');
  var chart = echarts.init(el);
  var today = new Date();
  var start = new Date(today); start.setDate(start.getDate() - 365);
  var hdata = D.heatmap_data;
  var range = [start.toISOString().slice(0,10), today.toISOString().slice(0,10)];
  chart.setOption({
    tooltip: { formatter: function(p){ return p.value[0] + ': ' + p.value[1] + ' 题'; }},
    visualMap: { min: 0, max: 8, show: false,
      inRange: { color: ['#161b22','#0e4429','#006d32','#26a641','#39d353'] }},
    calendar: {
      range: range, cellSize: [16, 16],
      itemStyle: { borderWidth: 3, borderColor: '#0d1117' },
      splitLine: { show: false },
      dayLabel: { color: '#8b949e', nameMap: 'cn', fontSize: 10 },
      monthLabel: { color: '#8b949e', fontSize: 11 },
      yearLabel: { show: false },
    },
    series: [{ type: 'heatmap', coordinateSystem: 'calendar', data: hdata }]
  });
})();

window.addEventListener('resize', function(){
  ['gauge','rounds','radar','trend','heatmap'].forEach(function(id){
    var c = echarts.getInstanceByDom(document.getElementById(id));
    if(c) c.resize();
  });
});
</script>
</body>
</html>"""


def _build_data(rows, stats, checkin_data, streak):
    """构建 HTML 模板所需的 JSON 数据。"""
    cat_stats = compute_category_stats(rows)
    categories = []
    for cat_name, cs in sorted(cat_stats.items(), key=lambda x: x[0]):
        pct = int(cs["done_r1"] / cs["total"] * 100) if cs["total"] else 0
        categories.append([cat_name, pct])

    daily = [[e["date"].strftime("%m/%d"), e["new"], e["review"]] for e in checkin_data[-60:]]
    heatmap_data = [[e["date"].isoformat(), e["total"]] for e in checkin_data]
    per_round = [stats["per_round"][rk] for rk in ROUND_KEYS]

    return {
        "total": stats["total"],
        "total_rounds": stats["total_rounds"],
        "done_rounds": stats["done_rounds"],
        "done_problems": stats["done_problems"],
        "rate": round(stats["rate"], 1),
        "per_round": per_round,
        "categories": categories,
        "daily": daily,
        "heatmap_data": heatmap_data,
        "streak": streak,
    }


def serve_web(rows, stats, checkin_data, streak, port: int = 8100):
    """启动本地 Web 看板服务。"""
    data = _build_data(rows, stats, checkin_data, streak)
    today_str = date.today().strftime("%Y-%m-%d")
    streak_class = "streak-fire" if streak >= 3 else ""

    html = _HTML_TEMPLATE
    html = html.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    html = html.replace("__DONE_ROUNDS__", str(stats["done_rounds"]))
    html = html.replace("__TOTAL_ROUNDS__", str(stats["total_rounds"]))
    html = html.replace("__RATE__", f"{stats['rate']:.1f}")
    html = html.replace("__DONE_ALL__", str(stats["done_problems"]))
    html = html.replace("__TOTAL__", str(stats["total"]))
    html = html.replace("__STREAK__", str(streak))
    html = html.replace("__STREAK_CLASS__", streak_class)
    html = html.replace("__TODAY__", today_str)

    html_bytes = html.encode("utf-8")

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.end_headers()
            self.wfile.write(html_bytes)

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
