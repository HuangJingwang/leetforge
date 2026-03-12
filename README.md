# LeetCode Hot100 每日同步工具

自动从 LeetCode CN 获取当天 AC 记录，筛选 Hot100 题目，一键更新刷题计划。自带炫彩终端面板、交互式 Web 看板、热力图、智能复习提醒等全套可视化功能。

## 功能一览

| 命令 | 说明 |
|------|------|
| `leetcode` | 同步今日刷题记录 |
| `leetcode --status` | 炫彩终端进度面板 + 智能复习提醒 |
| `leetcode --heatmap` | GitHub 风格刷题热力图 |
| `leetcode --web` | 交互式 Web 看板（ECharts 图表） |
| `leetcode --weakness` | 分类薄弱点分析（能力雷达） |
| `leetcode --report` | 生成每周报告 Markdown |
| `leetcode --badge` | 生成 SVG 进度徽章 |
| `leetcode --login` | 浏览器登录 LeetCode CN |
| `leetcode --cron 23:00` | 每天定时自动同步 |

## 核心功能

**自动同步**
- 调用 LeetCode CN GraphQL API 拉取当日 AC 提交
- 自动匹配 Hot100 题目，区分新题 / 复习
- 自动判断轮次（R1→R5），进度表写入完成日期
- 追加每日打卡记录，刷新进度看板

**智能复习提醒**
- 基于间隔重复（R2 +1天 / R3 +3天 / R4 +7天 / R5 +14天）
- 按紧急程度排序，在终端和 Web 看板中展示

**卡点检测**
- 自动检测提交 ≥ 3 次才 AC 的题目，写入打卡记录

**桌面通知**
- 同步完成后弹系统通知（macOS / Linux / Windows）

## 可视化功能

### 炫彩终端面板 `--status`

```
╔══════════════════════════════════════════════╗
║ 🎯 LeetCode Hot100 刷题进度                    ║
╚══════════════════════════════════════════════╝
╭── 总览 ──╮  ╭── 各轮进度 ──╮  ╭── 分类薄弱点 ──╮
│ 题目 101 │  │ R1 ████░ 21  │  │ 二分查找  ⚡   │
│ 轮次 4.2%│  │ R2 ░░░░░  0  │  │ 回溯     ⚡   │
│ 全通 0   │  │ ...          │  │ 动态规划  📝   │
╰──────────╯  ╰──────────────╯  ╰────────────────╯
```

用 [Rich](https://github.com/Textualize/rich) 库渲染，包含：总览面板、彩色进度条、分类薄弱点、智能复习提醒、新题建议。

### 刷题热力图 `--heatmap`

```
╭────── 刷题热力图（近 6 个月）──────╮
│ Mon ░ ░ ▒ ░ ░ █ ░ ░ ░ ░ ▓ ░ ░ ... │
│ Wed ░ ░ ░ ░ ░ ░ ░ ▒ ░ ░ ░ ░ ░ ... │
│ Fri ░ ▒ ░ ░ ░ ░ ░ ░ ░ ░ ░ ░ ░ ... │
│  Less ░ ▒ ▓ █ More                 │
╰─────────────────────────────────────╯
```

GitHub Contribution 风格，在终端中直接渲染，直观展示每日刷题密度。

### Web 看板 `--web`

```bash
leetcode --web          # 默认端口 8100
leetcode --web 3000     # 自定义端口
```

自动打开浏览器，展示 GitHub 暗色风格的交互式看板：

- **完成率仪表盘** — 环形百分比
- **各轮进度柱状图** — R1~R5 彩色柱状图
- **分类能力雷达图** — 15 个算法分类的掌握程度
- **每日刷题趋势** — 近 60 天新题/复习堆叠柱状图
- **年度热力图** — ECharts 日历热力图

### 分类薄弱点 `--weakness`

```
┌──────────┬──────┬────────────────┬──────┐
│ 分类     │ 题数 │ R1 完成率      │ 建议 │
├──────────┼──────┼────────────────┼──────┤
│ 二分查找 │  4   │ ░░░░░░░░ 0%    │ ⚡   │
│ 动态规划 │ 20   │ █████░░░ 45%   │ 📝   │
│ 堆       │  2   │ ██████░░ 50%   │ 📝   │
└──────────┴──────┴────────────────┴──────┘
```

包含按 R1 完成率排序的表格 + 能力雷达图（🔴 🟡 🟢 三色标识）。

### 每周报告 `--report`

自动生成周报 Markdown 文件到刷题计划文件夹，包含：
- 本周概况（打卡天数、新题、复习、总计、趋势对比）
- 总体进度
- 薄弱分类 TOP 3
- 下周建议

### SVG 进度徽章 `--badge`

生成 `progress_badge.svg` 到刷题计划文件夹，可嵌入 GitHub README：

```markdown
![LeetCode Hot100](./progress_badge.svg)
```

## 安装

```bash
git clone <repo-url>
cd leetcode_auto
./install.sh
```

安装脚本会自动检测 Python 环境、安装依赖、注册全局命令 `leetcode`。首次运行时还会自动下载浏览器引擎。

### 手动安装

```bash
pip install -e .
```

## 快速开始

```bash
# 1. 首次运行：自动创建文件夹 + 弹浏览器登录 + 同步
leetcode

# 2. 查看进度
leetcode --status

# 3. 打开 Web 看板
leetcode --web

# 4. 每天定时自动同步
leetcode --cron 23:00
```

## 项目结构

```
leetcode_auto/
├── install.sh              # 一键安装脚本
├── pyproject.toml          # 包配置 + 依赖 + 命令入口
├── setup.py                # pip 向后兼容
├── README.md
├── .env.example            # 手动配置模板
└── leetcode_auto/          # Python 包
    ├── __init__.py
    ├── config.py            # 配置加载
    ├── init_plan.py         # 题目列表 + 分类标签 + 模板生成
    ├── sync.py              # 核心同步 + CLI 入口
    ├── features.py          # Rich TUI / 热力图 / 徽章 / 薄弱点 / 周报
    └── web.py               # Web 看板（HTTP 服务 + ECharts）
```

## 数据目录

| 路径 | 说明 |
|------|------|
| `~/.leetcode_auto/cookies.json` | 登录凭证 |
| `~/.leetcode_auto/.env` | 可选手动配置 |
| `~/Desktop/刷题计划/` | 刷题计划文件夹（可通过 `PLAN_DIR` 自定义） |

## 常见问题

**Q: Cookie 过期了怎么办？**
直接运行 `leetcode`，会自动检测并弹浏览器重新登录。也可 `leetcode --login` 强制重登。

**Q: 如何修改计划文件夹路径？**
在 `~/.leetcode_auto/.env` 中添加 `PLAN_DIR=/your/path`。

**Q: 智能复习怎么算的？**
间隔重复：R1 完成后 1 天 → R2，3 天 → R3，7 天 → R4，14 天 → R5。`--status` 按逾期天数排序。

**Q: 卡点检测的标准？**
同一道题今日提交 ≥ 3 次才 AC 即为卡点。

**Q: Web 看板需要联网吗？**
需要（加载 ECharts CDN），数据本身全在本地。

**Q: 不想装浏览器引擎，可以手动配 Cookie 吗？**
可以。在 `~/.leetcode_auto/.env` 中填写 `LEETCODE_USERNAME`、`LEETCODE_SESSION`、`CSRF_TOKEN`。

**Q: 桌面通知没弹出？**
macOS 需在"系统设置 > 通知"中允许终端发通知。Linux 需安装 `libnotify`。
