# 【OfferPilot】我写了一个 LeetCode 刷题自动追踪工具，从此告别手动打卡

## 前言

最近在刷 LeetCode Hot100，给自己定了一个规矩：每道题刷 5 遍，按照艾宾浩斯遗忘曲线间隔复习。听起来很美好，但实际执行起来痛苦得不行。

每天刷完题之后，还要：

1. 打开桌面上的 Markdown 进度表，找到对应的题目，填上日期
2. 打开打卡文件，手动记录今天做了哪些题
3. 掰着手指头算哪些题明天该复习了
4. 更新一下进度看板的完成率

搞了一个礼拜之后我发现，**维护进度表的时间比做题还长**。更要命的是，复习计划完全靠脑子记，今天该复习「两数之和」还是「三数之和」？忘了。

作为一个程序员，这种事情肯定不能忍。于是我花了点时间搞了一个工具 —— **OfferPilot**，自动从 LeetCode 拉取 AC 记录，自动更新进度表，自动计算复习计划，甚至还有炫彩终端面板和 Web 看板。

**PS：这整个项目，从第一行代码到最后的部署上线，我都是用 Cursor + Claude Opus 4.6 模型完成的。** 我负责提需求、定方向、做决策，Cursor 负责找方案、写代码、调 Bug。后面文章中凡是涉及到具体的技术选型和代码实现，基本都是我把需求丢给 Cursor，它帮我找到了具体方案并实现的。说实话，这种"我说你写"的开发体验比我想象的丝滑得多，三四个小时就把整个项目从零搭到了功能完备。这也是我想分享这个项目的原因之一 —— **与其花时间手动造轮子，不如把需求描述清楚，让 AI 帮你又快又好地实现。**

本文会介绍这个工具的设计思路、核心实现、以及一些踩过的坑。

> 项目地址：[github.com/HuangJingwang/offerpilot](https://github.com/HuangJingwang/offerpilot)

## 需求分析

在动手之前，先梳理一下到底要解决什么问题。

### 痛点一：手动记录太繁琐

每天刷完题之后，我需要在桌面的 Markdown 文件里更新三个东西：

- **进度表**：101 道题 × 5 轮，得找到具体哪道题的哪一轮，填上日期
- **打卡记录**：今天做了哪些新题、复习了哪些旧题
- **进度看板**：总完成率、今日待办

手动维护这些东西，不仅慢，而且容易漏。

### 痛点二：复习计划靠脑子

我给自己定的复习间隔是：

| 轮次 | 间隔 | 含义 |
|:----:|:----:|:-----|
| R1 | — | 首次做题 |
| R2 | +1 天 | 次日巩固 |
| R3 | +3 天 | 短期记忆 |
| R4 | +7 天 | 中期巩固 |
| R5 | +14 天 | 长期记忆 |

但问题是，当你刷了三十多道题之后，每天该复习哪些、哪些已经逾期了，纯靠人脑根本算不过来。

### 痛点三：看不到进度

刷了一个月，到底完成了多少？哪些分类是薄弱点？打卡有没有断？这些信息分散在各个文件里，没有一个直观的视角。

### 理想方案

所以我想要的是这样一个工具：

1. **零手动输入**：自动从 LeetCode 获取今日 AC 记录
2. **智能复习**：自动计算今日到期的复习题目，按紧急程度排序
3. **进度可视化**：终端炫彩面板、Web 看板、热力图，一目了然
4. **后台运行**：设一次就不用管了，每天/每小时自动同步

## 技术方案

### 数据获取：LeetCode GraphQL API

LeetCode CN 提供了 GraphQL API，可以拿到用户最近的 AC 提交记录。核心 query 长这样：

```graphql
query recentAcSubmissions($userSlug: String!, $limit: Int) {
    recentACSubmissions(userSlug: $userSlug, limit: $limit) {
        id
        title
        titleSlug
        timestamp
    }
}
```

调用需要 `LEETCODE_SESSION` 和 `csrftoken` 两个 Cookie。这里有个问题：**怎么获取 Cookie？**

#### 方案一：手动复制

让用户打开浏览器 F12 → Application → Cookies，手动复制粘贴。

这也太不优雅了。而且 Cookie 是有过期时间的，过几天就得重新搞一次。

#### 方案二：浏览器自动登录

用 Playwright 打开一个真实的浏览器窗口，让用户正常登录（支持账号密码、微信扫码、GitHub OAuth 等所有方式），登录成功后自动从浏览器上下文中提取 Cookie 并保存。

我把这两个方案丢给 Cursor，它直接建议用方案二，并且找到了 Playwright 这个库来实现。用户只需要登录一次，后续 Cookie 过期了工具会自动检测并弹浏览器重新登录，整个过程对用户来说就是"弹个浏览器 → 登录 → 关掉"，非常丝滑。

```python
def browser_login() -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://leetcode.cn/accounts/login/")

        # 等待用户登录完成（URL 不再是 login 页面）
        page.wait_for_url(
            lambda url: "leetcode.cn" in url and "/accounts/login" not in url,
            timeout=300_000,
        )

        page.wait_for_timeout(2000)
        cookies = context.cookies("https://leetcode.cn")
        # 提取 LEETCODE_SESSION 和 csrftoken ...
```

### 进度表设计：Markdown 即数据库

存储方案上我跟 Cursor 讨论了一下，它建议用 SQLite 或者 JSON，但我坚持要用 **Markdown 表格**。原因很简单：

1. 用户可以直接用任何编辑器打开查看
2. 可以放在桌面上，随时瞄一眼
3. Git 友好，可以版本管理
4. 分享给别人也不需要任何工具

进度表的结构是这样的：

```markdown
| 序号 | 题目 | 难度 | R1 | R2 | R3 | R4 | R5 | 状态 | 最后完成日期 |
| ---: | --- | --- | :---: | :---: | :---: | :---: | :---: | --- | --- |
| 1 | [1. 两数之和](https://leetcode.cn/problems/two-sum/) | 简单 | 2026-03-10 | 2026-03-11 |   |   |   | 进行中 | 2026-03-11 |
```

R1~R5 列填的是完成日期而不是 ✓，这是为了后面计算复习间隔用的。

解析 Markdown 表格其实就是按 `|` 分割，没啥难度，但有个细节：**轮次的自动判定**。

当 LeetCode 告诉我"用户今天 AC 了两数之和"，我需要知道这是 R 几。这个需求我提给 Cursor 之后，它给出的方案很简洁：从 R1 到 R5 找第一个空的列填进去。

```python
def update_progress(rows, today_slugs, today_str):
    for row in rows:
        if row["title_slug"] not in today_slugs:
            continue
        for rk in ("r1", "r2", "r3", "r4", "r5"):
            if not row[rk] or row[rk] == "—":
                row[rk] = today_str  # 写入日期
                break
```

### 智能复习：间隔重复算法

这是整个工具最核心的价值，也是我一开始最想要的功能。我告诉 Cursor："我需要基于间隔重复的复习提醒，R1 完成后 1 天提醒 R2，3 天提醒 R3，以此类推"，它直接帮我实现了完整的到期计算逻辑。每次同步或查看状态时，会扫描进度表中所有题目，根据已完成的轮次和完成日期，计算出哪些题今天该复习了。

```python
REVIEW_INTERVALS = {"r2": 1, "r3": 3, "r4": 7, "r5": 14}

def _get_review_due(rows, today):
    due = []
    round_pairs = [("r1", "r2"), ("r2", "r3"), ("r3", "r4"), ("r4", "r5")]

    for row in rows:
        for prev_rk, next_rk in round_pairs:
            if not done(row[prev_rk]) or done(row[next_rk]):
                continue
            prev_date = parse_date(row[prev_rk])
            interval = REVIEW_INTERVALS[next_rk]
            due_date = prev_date + timedelta(days=interval)
            if today >= due_date:
                due.append({
                    "title": row["title"],
                    "round": next_rk,
                    "overdue": (today - due_date).days,
                })
            break  # 每道题只需要找到下一个待完成的轮次

    due.sort(key=lambda x: -x["overdue"])  # 逾期最久的排前面
    return due
```

这里有个小细节：每道题只找**下一个**该做的轮次。比如一道题 R1 和 R2 都做了，R3 还没做，那只看 R3 是否到期，不会同时提醒 R4、R5。

### 卡点检测：多次提交才 AC 的题

基本同步做完之后，我又提了一个需求："能不能自动检测哪些题我做得比较吃力？" Cursor 给出了"卡点检测"方案：通过拉取最近的**所有提交**（包括 Wrong Answer、Time Limit Exceeded 等），统计每道题的提交次数。如果一道题今天提交了 3 次以上才 AC，就标记为"卡点题目"。

这些卡点题目会写入打卡记录，方便后续重点复习。

### 后台守护：系统级定时任务

一开始 Cursor 用 Python 的 `schedule` 库实现了一个前台定时循环，但我觉得不行 —— 终端一关就没了，不够"无感"。我提了新需求："能不能注册到系统的定时任务里，关终端也不影响？" Cursor 直接帮我做了三个平台的适配：

| 平台 | 实现 |
|:-----|:-----|
| macOS | LaunchAgent (`~/Library/LaunchAgents/`) |
| Linux | systemd user timer |
| Windows | schtasks 计划任务 |

用户只需要运行一次 `leetcode --daemon 1h`，就注册到系统调度器了，关终端、关 IDE、甚至注销用户都不影响。支持灵活的频率配置：

```bash
leetcode --daemon 10m       # 每 10 分钟
leetcode --daemon 1h        # 每小时
leetcode --daemon 23:00     # 每天固定时间
```

以 macOS 为例，间隔模式用的是 `StartInterval`（秒级），固定时间用的是 `StartCalendarInterval`：

```python
if sched.mode == "interval":
    trigger = f"""
    <key>StartInterval</key>
    <integer>{sched.interval_seconds}</integer>"""
else:
    trigger = f"""
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{sched.hour}</integer>
        <key>Minute</key>
        <integer>{sched.minute}</integer>
    </dict>"""
```

每次执行完成后进程立即退出，不占任何资源。日志写到 `~/.leetcode_auto/sync.log`，随时可查。

## 可视化

核心功能做完之后，我问 Cursor："还有什么能让这个项目更炫的吗？" 它给我列了一堆建议：Rich 终端面板、Web 看板、热力图、SVG 徽章、薄弱点雷达图、每周报告... 我说"我全都要"，然后它就真的一个一个帮我实现了。

### Rich 终端面板

用 [Rich](https://github.com/Textualize/rich) 库渲染的炫彩终端面板，一条命令 `leetcode --status` 就能看到：

- 总览：题目数、完成率、连续打卡天数、预估完成日期
- 各轮进度条：R1~R5 五色进度条
- 分类薄弱点：按 R1 完成率排序，一眼看出哪个分类最弱
- 复习提醒：今日到期的题目，逾期天数用红/黄/绿标识
- 新题建议：R1 还没做的前 5 道题

### Web 看板

`leetcode --web` 会启动一个本地 HTTP 服务，用 ECharts 渲染五个交互式图表：

- **仪表盘**：环形完成率
- **柱状图**：R1~R5 各轮完成数
- **雷达图**：15 个算法分类的掌握程度
- **趋势图**：近 60 天新题/复习堆叠柱状图
- **年度热力图**：GitHub Contribution 风格

整个页面是 GitHub 暗色风格，数据通过内嵌 JSON 传给前端，不需要任何后端 API。

### 分类薄弱点

为了做分类分析，我给 Hot100 的每道题都标注了算法分类（动态规划、双指针、回溯、二叉树 等 15 个分类），存在代码里的一个字典中：

```python
SLUG_CATEGORY = {
    "two-sum": "哈希表",
    "add-two-numbers": "链表",
    "longest-substring-without-repeating-characters": "滑动窗口",
    "trapping-rain-water": "双指针",
    # ... 101 道题的分类标签
}
```

然后按分类统计完成率，`leetcode --weakness` 会输出一个按完成率排序的表格，附带一个文字版雷达图，薄弱环节一目了然。

## 项目结构

```
offerpilot/
├── install.sh              # 一键安装
├── pyproject.toml          # 包配置 + CLI 入口
└── leetcode_auto/
    ├── config.py            # 配置加载
    ├── init_plan.py         # 题目列表 + 分类标签 + 模板生成
    ├── sync.py              # 核心同步引擎 + CLI
    ├── daemon.py            # 后台守护：LaunchAgent / systemd / schtasks
    ├── features.py          # Rich TUI / 热力图 / 徽章 / 周报
    └── web.py               # Web 看板
```

整个项目用 `pip install -e .` 安装后，会注册一个全局命令 `leetcode`，所有功能都通过子命令访问。

## 踩过的坑

虽然代码是 Cursor 写的，但调试过程中还是踩了不少坑，这些坑大多是我在实际运行时发现的，然后扔回给 Cursor 修复。

### 1. Python 3.9 的类型标注

Cursor 一开始用的是 `str | None` 这种 Python 3.10+ 的语法，但我的机器是 3.9，直接报错：

```
TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
```

把报错扔给 Cursor，它立刻改成了 `Optional[str]`，虽然丑了点但兼容性好。

### 2. Playwright 的浏览器引擎

第一次运行的时候直接报了个 `FileNotFoundError`，Chromium 引擎没装。Cursor 一开始尝试直接调用引擎路径，不行，后来改成了用 subprocess 调 Playwright CLI 来安装，首次运行时自动检测并下载：

```python
subprocess.run(
    [sys.executable, "-m", "playwright", "install", "chromium"],
    check=True,
)
```

### 3. Cookie 有效性检测

不能假设保存的 Cookie 永远有效。每次同步前先调一下 `globalData` 查询，看看 `isSignedIn` 是不是 `true`。如果过期了就自动弹浏览器让用户重新登录，不需要手动去翻 Cookie。

### 4. Markdown 解析的边界情况

进度表的 R1~R5 列可能是空字符串、`—`、日期字符串、或者旧版本的 `✓`，解析时都得兼容。还有首次运行时文件压根不存在的情况，需要自动创建模板。

## 使用方式

```bash
# 安装
git clone https://github.com/HuangJingwang/offerpilot.git
cd offerpilot && pip install -e .

# 首次运行：弹浏览器登录 + 同步
leetcode

# 设置后台自动同步
leetcode --daemon 1h

# 查看进度
leetcode --status

# 更多
leetcode --heatmap      # 刷题热力图
leetcode --web          # Web 看板
leetcode --weakness     # 薄弱点分析
leetcode --report       # 每周报告
leetcode --badge        # SVG 进度徽章
```

## 关于 AI 辅助开发的体验

### 选择 Cursor，而不是 OpenClaw

其实我一开始是打算用 OpenClaw 的。上班的时候忙里偷闲，给 OpenClaw 丢了一个长任务，用的模型是 Codex + ChatGPT-5.4，结果跑了几次都不如人意，写出来的代码要么跑不通，要么逻辑对不上，之前还发了个沸点专门吐槽了一番。看来 OpenClaw 目前并不太适合这种需要长上下文、多轮迭代的编码任务。

后来换成 Cursor + Claude Opus 4.6，一个多小时大部分核心需求就全部做完了，体验上完全是两个级别。Cursor 的优势在于它**真的理解你的项目上下文** —— 你改了一个文件，它知道其他文件该怎么跟着改；你报了一个错，它能直接定位原因而不是瞎猜。

### 开发工作流

整个项目从零到功能完备，我大概花了三四个小时。我的工作流是这样的：

1. **我提需求**："我要自动同步 LeetCode 刷题记录到桌面 Markdown 文件"
2. **Cursor 出方案**：它找到了 LeetCode GraphQL API、Playwright、Rich 等技术栈
3. **我审方案、提修改**："Cookie 手动输入太麻烦了，能不能自动登录？""前台定时不行，要系统级后台任务""我全都要"
4. **Cursor 实现**：从代码到调试到修复 Bug 都是它搞定的
5. **我验收测试**：跑一遍看效果，发现问题扔回去改

这个过程中，AI 最强的地方不是"写代码快"，而是**技术方案的广度**。比如后台守护需要适配 macOS/Linux/Windows 三个平台的调度机制，这些细节如果我自己查文档可能得查半天，但 Cursor 直接就给了 LaunchAgent / systemd / schtasks 三套方案和完整实现。

当然也不是说完全不需要人。**需求的判断和取舍依然是人来做的**。比如存储用 Markdown 而不是数据库、复习间隔用 1-3-7-14 而不是其他策略、用户体验上的细节把控，这些都是我自己定的。AI 更像是一个技术功底极强的结对编程伙伴。

## 总结

这个工具解决了我在刷 Hot100 过程中最头疼的三个问题：**手动记录、复习遗忘、进度不可见**。

核心设计思路其实很简单：

1. **数据源**：LeetCode GraphQL API + Playwright 自动登录
2. **存储**：Markdown 文件（可读、可编辑、可 Git 管理）
3. **智能复习**：基于间隔重复算法，自动计算到期题目
4. **可视化**：Rich TUI + ECharts Web 看板
5. **持久化调度**：系统级定时任务，设一次管一辈子

整个项目用 Cursor + Claude Opus 4.6 三四个小时完成，从需求到代码到部署到这篇文章，AI 辅助开发的效率确实超出预期。

如果你也在刷 Hot100，或者有类似的刷题追踪需求，欢迎试用和 Star。也欢迎在评论区聊聊你们用 AI 辅助开发的体验。

> 项目地址：[github.com/HuangJingwang/offerpilot](https://github.com/HuangJingwang/offerpilot)
