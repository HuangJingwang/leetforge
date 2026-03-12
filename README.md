<div align="center">

# LeetForge

**刷题如锻造，每遍皆淬炼。**

你的 LeetCode Hot100 刷题锻造台 —— 自动同步、智能复习、炫彩看板，一站搞定。

[![Python](https://img.shields.io/badge/Python-3.9+-3776ab?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)]()

</div>

---

## Why LeetForge?

刷 Hot100 最痛的不是做题，而是 **记不住做了什么、不知道该复习什么、看不到进度**。

LeetForge 帮你解决这三个问题：

- **自动同步** — 每天自动拉取 LeetCode CN AC 记录，零手动输入
- **间隔复习** — 基于艾宾浩斯遗忘曲线，精准推送今日待复习题目
- **可视追踪** — 终端炫彩面板、Web 看板、热力图，进度一目了然

## Quick Start

```bash
# 克隆 & 安装
git clone https://github.com/HuangJingwang/leetcode_auto.git
cd leetcode_auto
pip install -e .

# 首次运行（自动弹浏览器登录 + 同步）
leetcode
```

首次运行会自动完成三件事：创建 `~/Desktop/刷题计划/` 文件夹 → 打开浏览器登录 LeetCode CN → 拉取今日 AC 记录并写入进度表。

## Features

### 一键同步

```bash
leetcode
```

自动拉取今日 AC 提交，匹配 Hot100 题目，智能判断当前轮次（R1→R5），在进度表中写入完成日期。同时追加每日打卡记录、刷新进度看板，完成后弹桌面通知。

### 炫彩终端面板

```bash
leetcode --status
```

```
╔══════════════════════════════════════════════╗
║       🎯 LeetCode Hot100 刷题进度             ║
╚══════════════════════════════════════════════╝
┌─ 总览 ──────────────────────────────────────┐
│ 题目总数    101                              │
│ 已完成轮次  21/505 (4.2%)                    │
│ 连续打卡    7 天 🔥                          │
└─────────────────────────────────────────────┘
┌─ 各轮进度 ──────────────────────────────────┐
│ R1  ━━━━━━━──────────────────  21/101       │
│ R2  ─────────────────────────   0/101       │
│ R3  ─────────────────────────   0/101       │
└─────────────────────────────────────────────┘
┌─ 今日到期复习（5 题）──────────────────────── ┐
│ R2  两数之和             今日到期             │
│ R2  三数之和             逾期 2 天            │
└─────────────────────────────────────────────┘
```

基于 [Rich](https://github.com/Textualize/rich) 渲染，包含总览、各轮进度条、分类薄弱点、智能复习提醒、新题建议。

### 刷题热力图

```bash
leetcode --heatmap
```

```
╭───── 刷题热力图（近 6 个月）─────╮
│ Mon ░ ░ ▒ ░ ░ █ ░ ░ ░ ░ ▓ ░ ░  │
│ Wed ░ ░ ░ ░ ░ ░ ░ ▒ ░ ░ ░ ░ ░  │
│ Fri ░ ▒ ░ ░ ░ ░ ░ ░ ░ ░ ░ ░ ░  │
│  Less ░ ▒ ▓ █ More              │
╰──────────────────────────────────╯
```

GitHub Contribution 风格，在终端中渲染每日刷题密度。

### Web 看板

```bash
leetcode --web          # 默认端口 8100
leetcode --web 3000     # 自定义端口
```

自动打开浏览器，GitHub 暗色风格交互式看板，包含：

| 图表 | 说明 |
|------|------|
| 仪表盘 | 环形完成率百分比 |
| 柱状图 | R1~R5 各轮完成数对比 |
| 雷达图 | 15 个算法分类掌握度 |
| 趋势图 | 近 60 天新题/复习堆叠柱状图 |
| 热力图 | ECharts 年度日历热力图 |

### 更多命令

| 命令 | 说明 |
|:-----|:-----|
| `leetcode --weakness` | 分类薄弱点分析 + 能力雷达图 |
| `leetcode --report` | 生成每周报告（Markdown） |
| `leetcode --badge` | 生成 SVG 进度徽章，可嵌入 GitHub Profile |
| `leetcode --login` | 重新打开浏览器登录 |
| `leetcode --cron 23:00` | 每天定时自动同步 |

## How It Works

```
┌───────────┐    GraphQL API    ┌──────────────┐
│ LeetCode  │ ◄──────────────── │  LeetForge   │
│    CN     │  fetch AC records │              │
└───────────┘                   │  ┌─ sync ──┐ │     ┌─────────────────────┐
                                │  │ match   │ │────►│ ~/Desktop/刷题计划/  │
                                │  │ Hot100  │ │     │  01_进度表.md        │
                                │  │ update  │ │     │  02_每日打卡.md      │
                                │  │ rounds  │ │     │  03_进度看板.md      │
                                │  └─────────┘ │     └─────────────────────┘
                                │              │
                                │  ┌─ views ─┐ │     ┌─────────────────────┐
                                │  │ Rich TUI│ │────►│ Terminal / Browser  │
                                │  │ Web UI  │ │     └─────────────────────┘
                                │  │ Heatmap │ │
                                │  └─────────┘ │
                                └──────────────┘
```

**间隔复习算法：**

| 轮次 | 间隔 | 含义 |
|:----:|:----:|:-----|
| R1 | — | 首次做题 |
| R2 | +1 天 | 次日巩固 |
| R3 | +3 天 | 短期记忆 |
| R4 | +7 天 | 中期巩固 |
| R5 | +14 天 | 长期记忆 |

LeetForge 自动追踪每道题的 R1~R5 完成日期，精准计算哪些题今日到期需要复习。

## Installation

### 一键安装（推荐）

```bash
git clone https://github.com/HuangJingwang/leetcode_auto.git
cd leetcode_auto
./install.sh
```

脚本自动检测 Python 环境、安装依赖、注册 `leetcode` 全局命令。

### 手动安装

```bash
git clone https://github.com/HuangJingwang/leetcode_auto.git
cd leetcode_auto
pip install -e .
```

> **依赖**：Python 3.9+ / requests / playwright / rich / schedule / python-dotenv
>
> 首次运行时自动下载 Chromium 浏览器引擎（用于自动登录）。

## Configuration

所有配置存放在 `~/.leetcode_auto/` 目录下：

| 文件 | 说明 |
|:-----|:-----|
| `cookies.json` | 浏览器登录后自动保存的凭证 |
| `.env` | 可选的手动配置文件 |

### 自定义计划路径

默认输出到 `~/Desktop/刷题计划/`，可通过环境变量修改：

```bash
# ~/.leetcode_auto/.env
PLAN_DIR=/your/custom/path
```

### 手动配置 Cookie（不使用浏览器登录）

```bash
# ~/.leetcode_auto/.env
LEETCODE_USERNAME=your-slug
LEETCODE_SESSION=xxx
CSRF_TOKEN=xxx
```

## Project Structure

```
leetcode_auto/
├── install.sh              # 一键安装脚本
├── pyproject.toml          # 包元信息 + 依赖 + CLI 入口
├── setup.py                # pip 向后兼容
├── .env.example            # 配置模板
└── leetcode_auto/
    ├── __init__.py
    ├── config.py            # 配置加载 & 凭证管理
    ├── init_plan.py         # Hot100 题目列表 + 分类标签 + 模板生成
    ├── sync.py              # 核心同步引擎 + CLI 入口
    ├── features.py          # 可视化：Rich TUI / 热力图 / 徽章 / 周报
    └── web.py               # Web 看板：HTTP 服务 + ECharts 前端
```

## FAQ

<details>
<summary><b>Cookie 过期了怎么办？</b></summary>

直接运行 `leetcode`，会自动检测并弹浏览器重新登录。也可 `leetcode --login` 强制重登。
</details>

<details>
<summary><b>智能复习是怎么算的？</b></summary>

基于间隔重复：R1 做完后 1 天到期 R2，3 天后到期 R3，7 天后到期 R4，14 天后到期 R5。`--status` 面板按逾期天数排序展示。
</details>

<details>
<summary><b>什么是"卡点题目"？</b></summary>

同一道题当天提交 ≥ 3 次才 AC，说明这道题有难度。LeetForge 自动检测并写入打卡记录，方便后续重点复习。
</details>

<details>
<summary><b>Web 看板需要联网吗？</b></summary>

需要加载 ECharts CDN 资源，数据本身全在本地。
</details>

<details>
<summary><b>不想装浏览器引擎怎么办？</b></summary>

可以在 `~/.leetcode_auto/.env` 中手动填写 Cookie，跳过浏览器登录。
</details>

<details>
<summary><b>支持哪些系统？</b></summary>

macOS / Linux / Windows 均可使用。桌面通知分别适配了 osascript / notify-send / PowerShell。
</details>

## Contributing

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 `git checkout -b feature/amazing-feature`
3. 提交修改 `git commit -m 'Add amazing feature'`
4. 推送分支 `git push origin feature/amazing-feature`
5. 提交 Pull Request

## License

[MIT](LICENSE) &copy; 2025 LeetForge
