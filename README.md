<div align="center">

# OfferPilot

**你的 AI 求职导航员。**

刷题同步、智能复习、AI 代码分析、简历优化、模拟面试 —— 从刷题到拿 Offer，全流程智能驾驶。

[![Python](https://img.shields.io/badge/Python-3.9+-3776ab?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)]()

</div>

---

## Why OfferPilot?

刷 Hot100 最痛的不是做题，而是 **记不住做了什么、不知道该复习什么、看不到进度、不知道代码能不能更优**。

OfferPilot 帮你解决这些问题：

- **自动同步** — 每天自动拉取 LeetCode CN AC 记录，零手动输入
- **间隔复习** — 基于艾宾浩斯遗忘曲线，精准推送今日待复习题目
- **AI 分析** — 自动对比官方题解，给出代码优化建议和改进代码
- **AI 对话** — 随时询问刷题进度、制定计划、获取算法建议
- **Web 看板** — 6 标签页交互式 Web 界面，进度/复习/优化/对话一站查看

## Quick Start

```bash
# 克隆 & 安装
git clone https://github.com/HuangJingwang/offerpilot.git
cd leetcode_auto
pip install -e .

# 首次运行（自动弹浏览器登录 + 同步）
leetcode

# 打开 Web 看板查看所有数据
leetcode --web
```

首次运行会自动完成三件事：初始化数据目录 → 打开浏览器登录 LeetCode CN → 拉取今日 AC 记录并写入进度表。

数据统一存储在 `~/.leetcode_auto/data/` 下，通过 `leetcode --web` 在浏览器中查看所有信息。

```bash
# 设置后台自动同步（关终端不影响）
leetcode --daemon 1h        # 每小时
leetcode --daemon 23:00     # 或每天固定时间
```

## Features

### 一键同步 + AI 代码分析

```bash
leetcode
```

自动拉取今日 AC 提交，匹配 Hot100 题目，智能判断当前轮次（R1→R5），写入完成日期。同时：
- 追加每日打卡记录、刷新进度看板
- **自动分析每道提交的 runtime/memory 百分位**，低于 50% 的题目标记为待优化
- **AI 自动获取官方题解对比分析**，给出时间/空间复杂度对比、优化建议和改进代码
- 仅在有新 AC 同步时弹桌面通知，无 AC 时静默跳过

### Web 看板

```bash
leetcode --web          # 默认端口 8100
leetcode --web 3000     # 自定义端口
```

自动打开浏览器，GitHub 暗色风格交互式看板，包含 **6 个标签页**：

| 标签页 | 内容 |
|--------|------|
| **Dashboard** | 统计卡片、今日新题/复习推荐、完成率仪表盘、各轮进度图、分类雷达图、趋势图、热力图 |
| **AI Chat** | AI 对话助手，基于刷题数据回答问题、制定计划、解答算法疑问，对话记录自动保存 |
| **Progress** | 100 题完整进度表，支持搜索、按难度/分类/状态筛选，一键清除筛选条件 |
| **Review** | 今日待复习题目列表，按逾期天数排序，导航栏显示待复习数量 |
| **Check-in** | 每日打卡时间线 + 近 30 天趋势折线图 |
| **Optimize** | AI 代码分析结果，展示复杂度对比、优化建议、改进代码，可展开查看原始代码 |

看板支持 **30 秒自动刷新**，后台同步完成后页面自动更新，无需手动刷新。移动端自适应底部导航栏。

> 所有数据存储在 `~/.leetcode_auto/data/`，不再在桌面创建 Markdown 文件。已有桌面数据会在首次运行时自动迁移。

### AI 对话助手

```bash
leetcode --chat         # 终端交互式对话
```

或在 Web 看板的 **AI Chat** 标签页中直接对话。AI 助手基于你的真实刷题数据，可以：

- 告诉你今天该刷什么题
- 分析你的薄弱分类并制定专项突破计划
- 回答算法和数据结构问题
- 帮你制定每周/每月刷题计划

对话记录自动保存，CLI 和 Web 共享同一份历史，输入 `clear` 可清空。

### 每日提醒

```bash
leetcode --remind              # 立即查看今日待刷/待复习题目
leetcode --remind-daemon       # 注册每日提醒（10:00/17:00/22:00 自动推送）
leetcode --remind-daemon status
leetcode --remind-daemon stop
```

每天三个时间点自动推送桌面通知，提醒你今日需要复习的题目和推荐的新题，不错过任何复习窗口。

### 后台守护

```bash
leetcode --daemon 30m       # 每 30 分钟同步一次
leetcode --daemon 1h        # 每小时同步一次
leetcode --daemon 23:00     # 每天 23:00 同步
leetcode --daemon status    # 查看后台任务状态
leetcode --daemon stop      # 卸载后台任务
```

支持分钟(`10m`)、小时(`2h`)、固定时间(`23:00`)三种格式，注册一次即永久生效，**关闭终端、注销用户都不影响**。按系统自动适配：

| 系统 | 底层实现 | 管理方式 |
|:-----|:---------|:---------|
| macOS | LaunchAgent | `~/Library/LaunchAgents/` |
| Linux | systemd user timer | `~/.config/systemd/user/` |
| Windows | 计划任务 (schtasks) | 任务计划程序 |

日志输出到 `~/.leetcode_auto/sync.log`，随时可查。

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

### 全部命令

| 命令 | 说明 |
|:-----|:-----|
| `leetcode` | 同步今日刷题记录 + AI 代码分析 |
| `leetcode --web` | 打开 Web 看板（6 标签页全功能界面） |
| `leetcode --chat` | AI 对话助手（终端交互式） |
| `leetcode --status` | 炫彩终端进度面板 |
| `leetcode --heatmap` | GitHub 风格刷题热力图 |
| `leetcode --optimize` | 查看待优化题目列表 |
| `leetcode --weakness` | 分类薄弱点分析 + 能力雷达图 |
| `leetcode --report` | 生成每周报告（Markdown） |
| `leetcode --badge` | 生成 SVG 进度徽章，可嵌入 GitHub Profile |
| `leetcode --login` | 重新打开浏览器登录 |
| `leetcode --daemon <schedule>` | 后台定时同步（30m / 1h / 23:00 / status / stop） |
| `leetcode --remind` | 查看今日待刷/待复习题目并推送通知 |
| `leetcode --remind-daemon` | 每日提醒定时任务（start / status / stop） |
| `leetcode --cron 23:00` | 前台定时同步（终端需保持运行） |

## How It Works

```
                                 ┌──────────────┐
┌───────────┐   submissionList   │  OfferPilot   │     ┌──────────────────────┐
│ LeetCode  │ ◄───────────────── │              │     │ ~/.leetcode_auto/    │
│    CN     │  GraphQL API       │  ┌─ sync ──┐ │────►│  data/进度表.md       │
└───────────┘                    │  │ match   │ │     │  data/打卡.md         │
               submissionDetail  │  │ Hot100  │ │     │  data/optimizations   │
              ◄───────────────── │  │ update  │ │     │  data/chat_history    │
                                 │  └─────────┘ │     └──────────────────────┘
┌───────────┐   official soln    │              │
│    AI     │ ◄───────────────── │  ┌─ AI ────┐ │     ┌──────────────────────┐
│  Claude / │   code analysis    │  │ analyze │ │────►│ Browser (--web)      │
│  OpenAI   │ ◄───────────────── │  │ chat    │ │     │ Terminal (--status)  │
└───────────┘   chat response    │  └─────────┘ │     │ Terminal (--chat)    │
                                 └──────────────┘     └──────────────────────┘
```

**间隔复习算法：**

| 轮次 | 间隔 | 含义 |
|:----:|:----:|:-----|
| R1 | — | 首次做题 |
| R2 | +1 天 | 次日巩固 |
| R3 | +3 天 | 短期记忆 |
| R4 | +7 天 | 中期巩固 |
| R5 | +14 天 | 长期记忆 |

**AI 代码分析流程：**

1. 同步时检测 AC 提交的 runtime/memory 百分位，低于 50% 标记为待优化
2. 通过 LeetCode API 获取官方题解
3. 调用 AI（Claude / OpenAI）对比用户代码与最优解
4. 输出：复杂度对比、问题分析、优化建议、改进后完整代码

## Installation

### 一键安装（推荐）

```bash
git clone https://github.com/HuangJingwang/offerpilot.git
cd leetcode_auto
./install.sh
```

脚本自动检测 Python 环境、安装依赖、注册 `leetcode` 全局命令。

### 手动安装

```bash
git clone https://github.com/HuangJingwang/offerpilot.git
cd leetcode_auto
pip install -e .
```

> **依赖**：Python 3.9+ / requests / playwright / rich / schedule / python-dotenv
>
> 首次运行时自动下载 Chromium 浏览器引擎（用于自动登录）。

## Configuration

所有配置和数据存放在 `~/.leetcode_auto/` 目录下：

| 文件/目录 | 说明 |
|:----------|:-----|
| `cookies.json` | 浏览器登录后自动保存的凭证 |
| `.env` | 配置文件（AI、数据路径等） |
| `data/` | 进度表、打卡记录、优化建议等数据文件 |
| `chat_history.json` | AI 对话记录（CLI 和 Web 共享） |
| `sync.log` | 后台同步日志 |

### AI 配置

在 `~/.leetcode_auto/.env` 中配置 AI Provider（支持 Claude 和 OpenAI 及兼容接口）：

```bash
# OpenAI 或兼容接口
AI_PROVIDER=openai
AI_API_KEY=sk-xxx
AI_MODEL=gpt-4o                       # 可选，留空用默认
AI_BASE_URL=https://api.openai.com/v1 # 可选，自定义 API 地址

# 或使用 Claude
AI_PROVIDER=claude
AI_API_KEY=sk-ant-xxx
AI_MODEL=claude-sonnet-4-20250514     # 可选，留空用默认
```

未配置 AI 时，同步和看板正常工作，仅跳过 AI 分析和对话功能。

### 自定义数据路径

```bash
# ~/.leetcode_auto/.env
PLAN_DIR=/your/custom/path
```

> **从旧版迁移**：如果你之前使用的是桌面版（`~/Desktop/刷题计划/`），首次运行新版时会自动将数据迁移到 `~/.leetcode_auto/data/`，桌面旧文件可手动删除。

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
└── leetcode_auto/
    ├── __init__.py
    ├── config.py            # 配置加载 & 凭证管理 & AI 配置 & 数据迁移
    ├── init_plan.py         # Hot100 题目列表 + 分类标签 + 模板生成
    ├── sync.py              # 核心同步引擎 + 代码优化检测 + CLI 入口
    ├── ai_analyzer.py       # AI 代码分析 + 对话功能（支持 Claude / OpenAI）
    ├── daemon.py            # 后台守护：LaunchAgent / systemd / schtasks
    ├── features.py          # 可视化：Rich TUI / 热力图 / 徽章 / 周报
    └── web.py               # Web 看板：6 标签页 SPA + ECharts + AI Chat
```

## FAQ

<details>
<summary><b>Cookie 过期了怎么办？</b></summary>

- **交互模式**（直接运行 `leetcode`）：自动检测 Cookie 状态，过期则弹浏览器重新登录。也可 `leetcode --login` 强制重登。
- **后台 daemon 模式**：不会弹浏览器（无交互环境），仅打印提示 `Cookie 已过期，请手动运行 leetcode --login 重新登录`，同步跳过。请在终端执行一次 `leetcode --login` 刷新凭证。
</details>

<details>
<summary><b>智能复习是怎么算的？</b></summary>

基于间隔重复：R1 做完后 1 天到期 R2，3 天后到期 R3，7 天后到期 R4，14 天后到期 R5。`--status` 面板和 Web 看板的 Review 标签页按逾期天数排序展示。
</details>

<details>
<summary><b>AI 分析需要什么配置？</b></summary>

在 `~/.leetcode_auto/.env` 中设置 `AI_PROVIDER` 和 `AI_API_KEY` 即可。支持 OpenAI、Claude 以及任何兼容 OpenAI 接口的第三方服务（通过 `AI_BASE_URL` 指定地址）。未配置时 AI 功能自动跳过，不影响同步和看板使用。
</details>

<details>
<summary><b>AI 对话记录会保存吗？</b></summary>

会。对话记录保存在 `~/.leetcode_auto/chat_history.json`，最多保留最近 50 轮。CLI（`--chat`）和 Web（AI Chat 标签页）共享同一份历史。在 CLI 输入 `clear` 或 Web 点击"清空"按钮可重置。
</details>

<details>
<summary><b>什么是"卡点题目"？</b></summary>

同一道题当天提交 ≥ 3 次才 AC，说明这道题有难度。OfferPilot 自动检测并写入打卡记录，方便后续重点复习。
</details>

<details>
<summary><b>Web 看板需要联网吗？</b></summary>

需要加载 ECharts 和 marked.js CDN 资源，刷题数据本身全在本地。AI 对话功能需要联网调用 API。
</details>

<details>
<summary><b>桌面上的旧 Markdown 文件怎么办？</b></summary>

新版数据统一存储在 `~/.leetcode_auto/data/`，首次运行会自动迁移桌面旧数据。迁移后桌面文件可手动删除。
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

[MIT](LICENSE) &copy; 2025 OfferPilot
