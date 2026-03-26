<div align="center">

[English](README.md) | **中文**

# BrushUp

**刷题、复习、简历，一个工具搞定。**

[![Python](https://img.shields.io/badge/Python-3.9+-3776ab?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)]()

自动同步 LeetCode 刷题记录，间隔复习，AI 代码分析，简历优化，模拟面试。

</div>

---

## 功能概览

**刷题方面：**
- 自动拉取 LeetCode CN 的 AC 记录，不用手动打卡
- 可配置的间隔复习（默认 5 轮：+1/3/7/14 天），到期自动提醒
- AI 对比官方题解，给出复杂度对比和改进代码
- 每道题每轮提交都有 AI 分析记录，可在进度表中查看
- 3 个内置题单：Hot 100、剑指 Offer 75、Top Interview 150
- 同分类题目集中推荐，薄弱分类优先
- GitHub 风格热力图、趋势分析、连续打卡统计

**简历 & 面试：**
- LapisCV Markdown 模板 + 实时预览
- AI 简历分析，对话式修改（AI 直接改简历内容），版本历史可回退
- 多份简历管理（如"后端简历""全栈简历"）
- 一键根据简历生成面试题
- AI 模拟面试官，逐题追问
- 面试结束生成评估报告（6 维度评分）

## 快速开始

```bash
git clone https://github.com/HuangJingwang/brushup.git
cd brushup
pip install -e .

leetcode --web     # 打开 Web 看板，在页面上完成登录
```

## Web 看板

`leetcode --web` 打开本地看板。支持中英文切换、深色/浅色主题、键盘快捷键（1-9）、30 秒自动刷新、移动端自适应。

### 总览
统计卡片、今日任务、完成率仪表盘、各轮进度、分类雷达、热力图、复习日历、趋势分析。

![Dashboard](screenshots/dashboard.png)

### 进度表
完整题目表，搜索 + 多维筛选 + 笔记 + 每轮 AI 分析 + CSV 导出。

![Progress](screenshots/progress.png)

### AI 对话
基于刷题数据的 AI 助手，跨场景共享记忆。

![AI Chat](screenshots/chat.png)

### 待复习
今日到期复习题目，按逾期天数排序。

![Review](screenshots/review.png)

### 简历优化
模板下载、LapisCV 预览、AI 分析、对话编辑、版本历史、多份简历管理。

![Resume](screenshots/resume.png)

### 模拟面试
根据简历生成面试题 + AI 面试官 + 评估报告。

![Mock Interview](screenshots/interview.png)

### 设置
题单切换、轮数、间隔、截止日、每日进度计算、AI 用量统计。

![Settings](screenshots/settings.png)

## 主要特点

### AI 代码分析

每次同步检测 runtime/memory 百分位，低于 50% 的题目自动获取官方题解对比，输出复杂度分析和改进代码。每道题每轮的提交都有独立的 AI 分析记录。

### 可配置的学习计划

| 配置项 | 默认值 | 可选范围 |
|:-------|:-------|:---------|
| 轮数 | 5 | 2-10 |
| 间隔 | 1, 3, 7, 14 天 | 自定义 |
| 题单 | Hot 100 | Hot 100 / 剑指 Offer 75 / Top 150 |
| 截止日 | 不限 | 设定后自动计算每日进度 |

### 跨场景记忆

刷题对话、简历分析、模拟面试共享记忆。面试中暴露的薄弱点会回流到刷题推荐。对话过长时自动压缩。

### 简历工作流

粘贴简历 → LapisCV 预览 → AI 分析 → 对话式修改（"用 STAR 法则改写工作经历"）→ 简历自动更新 → 版本历史可回退。支持多份简历独立管理。

### 模拟面试

根据简历生成面试题 → 开始面试 → AI 逐题提问、追问、引导 → 结束 → 生成评估报告（项目深挖/技术原理/系统设计/算法/沟通/应变 各 10 分）。

## AI 配置

在 `~/.leetcode_auto/.env` 中添加（支持 OpenAI / Claude / 兼容接口）：

```bash
AI_PROVIDER=openai
AI_API_KEY=sk-xxx
AI_MODEL=gpt-4o              # 可选
AI_BASE_URL=https://...      # 可选，第三方接口地址
```

不配置 AI 也能正常使用刷题同步和看板，AI 功能自动跳过。

## 全部命令

```
leetcode                   同步今日刷题 + AI 分析
leetcode --web             Web 看板（完整界面）
leetcode --chat            AI 对话（终端）
leetcode --status          终端进度面板
leetcode --heatmap         刷题热力图
leetcode --optimize        待优化题目
leetcode --weakness        薄弱点分析
leetcode --report          每周报告
leetcode --badge           SVG 进度徽章
leetcode --login           浏览器登录
leetcode --daemon <spec>   后台同步（30m / 1h / 23:00 / status / stop）
leetcode --remind          今日待刷/待复习
leetcode --remind-daemon   每日通知（start / status / stop）
```

## 项目结构

```
leetcode_auto/
├── cli.py              # CLI 入口 + 所有命令
├── config.py           # 配置管理、计划设置、AI 配置
├── leetcode_api.py     # LeetCode API、登录、提交分析
├── progress.py         # 进度表解析、统计、复习计算
├── sync.py             # 同步逻辑、打卡、看板
├── ai_analyzer.py      # AI 调用、对话、用量追踪
├── memory.py           # 跨对话共享记忆 + 压缩
├── problem_data.py     # 题目笔记、计时、AI 分析
├── problem_lists.py    # Hot100 / Offer75 / Top150 题单定义
├── resume.py           # 简历管理、分析、面试
├── features.py         # Rich 终端、热力图、徽章、周报
├── init_plan.py        # 题目分类、模板生成
├── daemon.py           # 后台守护：LaunchAgent / systemd / schtasks
└── web.py              # Web 单页应用 + HTTP 服务
```

## FAQ

<details>
<summary><b>Cookie 过期了怎么办？</b></summary>
在 Web 侧边栏点击登录按钮，或运行 <code>leetcode --login</code>。
</details>

<details>
<summary><b>对话记录会保存吗？</b></summary>
会。刷题/简历/面试各自保存，共享跨场景记忆。过长时自动压缩。
</details>

<details>
<summary><b>需要联网吗？</b></summary>
ECharts/marked.js 从 CDN 加载，刷题数据在本地。AI 功能需要联网。
</details>

<details>
<summary><b>AI 费用怎么看？</b></summary>
每次调用的 token 用量记录在 ~/.leetcode_auto/ai_usage.json，保留 90 天。
</details>

## Contributing

欢迎提交 Issue 和 Pull Request。

## License

[MIT](LICENSE) &copy; 2025 BrushUp
