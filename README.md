<div align="center">

# BrushUp

**Study smarter, not harder.**

[![Python](https://img.shields.io/badge/Python-3.9+-3776ab?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)]()

LeetCode auto-sync, spaced repetition, AI code review, resume polish, mock interview.

</div>

---

## What it does

**LeetCode study:**
- Auto-sync AC submissions from LeetCode CN — no manual tracking
- Configurable spaced repetition (default 5 rounds: +1/3/7/14 days), auto-remind when due
- AI compares your code to official solutions, shows complexity diff and improved version
- Per-problem notes, AI review history for every round
- 3 built-in problem lists: Hot 100, Sword Offer 75, Top Interview 150
- Same-category daily recommendations (weakest topics first)
- GitHub-style contribution heatmap, trend analysis, streak tracking

**Resume & Interview:**
- LapisCV Markdown template with live preview
- AI resume analysis, chat-to-edit (AI modifies resume directly), version history with rollback
- Multiple resume profiles (e.g. "Backend", "Full-stack")
- One-click interview question generation from resume
- AI mock interviewer with follow-up questions
- Structured interview report (6-dimension scoring)

## Quick start

```bash
git clone https://github.com/HuangJingwang/brushup.git
cd leetcode_auto && pip install -e .

leetcode --web     # opens web dashboard, login from browser
```

## Web Dashboard

`leetcode --web` opens a local dashboard with 9 tabs:

| Tab | What's in it |
|:----|:-------------|
| **Dashboard** | Stats cards, today's tasks, completion gauge, round progress, category radar, daily trend, GitHub-style heatmap, review calendar, trend analysis |
| **AI Chat** | Study assistant with full context of your progress |
| **Progress** | Full problem table with search, multi-filter, notes, per-round AI review history, CSV export |
| **Review** | Today's due problems sorted by overdue days |
| **Check-in** | Daily timeline + 30-day trend chart |
| **Optimize** | AI code analysis: complexity comparison, suggestions, rewritten code |
| **Resume** | Template download, LapisCV preview, AI analysis, chat-to-edit, version history |
| **Mock Interview** | Generated questions + AI interviewer + evaluation report |
| **Settings** | Problem list, rounds, intervals, deadline, daily pace calculator |

Features: EN/ZH toggle, dark/light theme, keyboard shortcuts (1-9), 30s auto-refresh, mobile responsive, login/logout from browser.

## Key features

### AI code analysis
Each sync checks runtime/memory percentile. Below 50%? AI fetches the official solution, compares your code, outputs: complexity diff → specific issues → improved code.

Every round's submission gets a per-problem AI review, viewable in the progress table.

### Configurable study plan
| Setting | Default | Options |
|:--------|:--------|:--------|
| Rounds | 5 | 2–10 |
| Intervals | 1, 3, 7, 14 days | Custom |
| Problem list | Hot 100 | Hot 100 / Sword Offer 75 / Top 150 |
| Deadline | None | Set date → auto-calculate daily pace |

### Cross-scene memory
Study chat, resume analysis, and mock interview share memory. Weak points found in interview flow back to study recommendations. History auto-compresses when long.

### Resume workflow
Paste resume → Preview (LapisCV style) → AI Analyze → Chat to improve ("rewrite my work experience with STAR method") → Resume auto-updates → Version history for rollback.

Multiple resume profiles, each with independent content/analysis/chat.

### Mock interview
Generate questions from resume → Start interview → AI asks one question at a time, follows up, gives hints → End → Generate evaluation report with 6-dimension scoring.

## AI configuration

Add to `~/.leetcode_auto/.env` (supports OpenAI / Claude / compatible APIs):

```bash
AI_PROVIDER=openai
AI_API_KEY=sk-xxx
AI_MODEL=gpt-4o              # optional
AI_BASE_URL=https://...      # optional, for third-party endpoints
```

Works without AI — sync and dashboard are fully functional, AI features are skipped.

## All commands

```
leetcode                   sync today's submissions + AI analysis
leetcode --web             web dashboard (full UI)
leetcode --chat            AI chat (terminal)
leetcode --status          terminal progress panel
leetcode --heatmap         contribution heatmap
leetcode --optimize        optimization suggestions
leetcode --weakness        category weakness analysis
leetcode --report          weekly report
leetcode --badge           SVG progress badge
leetcode --login           browser login
leetcode --daemon <spec>   background sync (30m / 1h / 23:00 / status / stop)
leetcode --remind          today's study/review list
leetcode --remind-daemon   daily notifications (start / status / stop)
```

## Architecture

```
leetcode_auto/
├── cli.py              # CLI entry + all commands
├── config.py           # Configuration, plan settings, AI config
├── leetcode_api.py     # LeetCode API, auth, browser login
├── progress.py         # Progress table, stats, review calculation
├── sync.py             # Sync logic, checkin, dashboard
├── ai_analyzer.py      # AI calls, chat, usage tracking
├── memory.py           # Cross-chat shared memory + compression
├── problem_data.py     # Per-problem notes, timer, AI reviews
├── problem_lists.py    # Hot100, Offer75, Top150 definitions
├── resume.py           # Resume management, analysis, interview
├── features.py         # Rich TUI, heatmap, badge, report
├── init_plan.py        # Problem categories, template generation
├── daemon.py           # Background: LaunchAgent / systemd / schtasks
└── web.py              # Web SPA: HTML/CSS/JS + HTTP server
```

## FAQ

<details>
<summary><b>Cookie expired?</b></summary>
Click the login button in the web sidebar, or run <code>leetcode --login</code>.
</details>

<details>
<summary><b>Chat history saved?</b></summary>
Yes. Study/resume/interview each save independently, with shared cross-scene memory. Auto-compressed when long.
</details>

<details>
<summary><b>Need internet?</b></summary>
ECharts/marked.js loaded from CDN. Study data is local. AI features need internet.
</details>

<details>
<summary><b>AI costs?</b></summary>
Token usage tracked per-call in ~/.leetcode_auto/ai_usage.json (90-day retention). Available in dashboard data.
</details>

## Contributing

Issues and PRs welcome.

## License

[MIT](LICENSE) &copy; 2025 BrushUp
