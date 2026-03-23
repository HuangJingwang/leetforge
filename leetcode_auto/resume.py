"""简历分析与优化：LaTeX 模板、AI 分析、对话式改进。"""

import json
from pathlib import Path
from typing import Optional

from .config import DATA_DIR, get_ai_config
from .ai_analyzer import call_ai_messages

# ---------------------------------------------------------------------------
# 数据文件
# ---------------------------------------------------------------------------

RESUME_FILE = DATA_DIR / "resume_content.txt"
RESUME_ANALYSIS_FILE = DATA_DIR / "resume_analysis.json"
RESUME_CHAT_FILE = DATA_DIR / "resume_chat_history.json"

# ---------------------------------------------------------------------------
# LaTeX 简历模板
# ---------------------------------------------------------------------------

LATEX_TEMPLATE = r"""%!TEX program = xelatex
\documentclass[11pt,a4paper]{article}

% ==================== 宏包 ====================
\usepackage[margin=1.8cm]{geometry}
\usepackage{ctex}                    % 中文支持（XeLaTeX 编译）
\usepackage{titlesec}
\usepackage{enumitem}
\usepackage{hyperref}
\usepackage{xcolor}
\usepackage{tabularx}
\usepackage{multicol}

% ==================== 样式 ====================
\pagestyle{empty}
\setlength{\parindent}{0pt}
\definecolor{accent}{HTML}{2563EB}
\definecolor{textgray}{HTML}{4B5563}
\hypersetup{colorlinks=true,urlcolor=accent,linkcolor=accent}

\titleformat{\section}{\large\bfseries\color{accent}}{}{0em}{}[\color{accent}\titlerule]
\titlespacing{\section}{0pt}{14pt}{6pt}

% 条目宏：公司/学校 | 角色 | 补充 | 时间
\newcommand{\entry}[4]{%
  \textbf{#1} \hfill {\small\color{textgray}#4} \\
  {\color{textgray}#2\hfill #3} \vspace{2pt}
}

% ==================== 正文 ====================
\begin{document}

% ---------- 个人信息 ----------
\begin{center}
  {\LARGE\bfseries 张三} \\[6pt]
  {\color{textgray}
    \href{mailto:zhangsan@example.com}{zhangsan@example.com} $\cdot$
    138-0000-0000 $\cdot$
    \href{https://github.com/zhangsan}{github.com/zhangsan} $\cdot$
    \href{https://linkedin.com/in/zhangsan}{LinkedIn}
  }
\end{center}

% ---------- 教育背景 ----------
\section{教育背景}

\entry{XX 大学}{计算机科学与技术 · 硕士}{GPA：3.8 / 4.0}{2022.09 -- 2025.06}
\begin{itemize}[nosep,leftmargin=1.5em,topsep=2pt]
  \item 核心课程：高级算法、分布式系统、数据库内核、机器学习
  \item 一等学业奖学金（前 5\%），校级优秀毕业生
\end{itemize}

\vspace{4pt}
\entry{XX 大学}{软件工程 · 学士}{GPA：3.6 / 4.0}{2018.09 -- 2022.06}

% ---------- 工作/实习经历 ----------
\section{工作经历}

\entry{XX 科技有限公司}{后端开发工程师（实习）}{Go / MySQL / Redis / Kafka}{2024.06 -- 2024.09}
\begin{itemize}[nosep,leftmargin=1.5em,topsep=2pt]
  \item 主导用户中心微服务重构，将单体服务拆分为 5 个独立模块，接口 QPS 提升 40\%
  \item 设计基于 Redis + Lua 的分布式限流方案，稳定支撑日均 500 万次 API 调用
  \item 定位并优化 12 条慢查询 SQL，核心接口 P99 延迟从 800ms 降至 120ms
\end{itemize}

% ---------- 项目经历 ----------
\section{项目经历}

\entry{分布式键值存储引擎}{个人项目 · Go}{Raft / LSM-Tree / gRPC}{2024.03 -- 2024.05}
\begin{itemize}[nosep,leftmargin=1.5em,topsep=2pt]
  \item 基于 Raft 共识算法实现 3 节点数据复制，支持自动选主、日志压缩和快照恢复
  \item 存储层采用 LSM-Tree + WAL 架构，写入吞吐量达 10 万 ops/s
  \item 完整单元测试 + 混沌测试（网络分区、节点宕机），代码覆盖率 85\%
\end{itemize}

\vspace{4pt}
\entry{OfferPilot — LeetCode 刷题锻造台}{开源项目 · Python}{ECharts / GraphQL / AI}{2025.01 -- 至今}
\begin{itemize}[nosep,leftmargin=1.5em,topsep=2pt]
  \item 自动同步 LeetCode 刷题记录，基于间隔重复算法推送复习计划
  \item 接入 AI 对比官方题解，自动分析代码复杂度并给出优化建议
  \item 交互式 Web 看板（7 标签页），涵盖进度追踪、数据可视化、AI 对话
\end{itemize}

% ---------- 专业技能 ----------
\section{专业技能}

\begin{tabularx}{\textwidth}{@{}l@{\hspace{12pt}}X@{}}
  \textbf{编程语言} & Go, Python, Java, C++, SQL, JavaScript / TypeScript \\[2pt]
  \textbf{框架 / 中间件} & Gin, Spring Boot, React, gRPC, Protobuf \\[2pt]
  \textbf{基础设施} & MySQL, Redis, Kafka, Docker, Kubernetes, Linux \\[2pt]
  \textbf{工具链} & Git, GitHub Actions, Prometheus, Grafana, Nginx \\[2pt]
  \textbf{算法能力} & LeetCode Hot100 $\times$ 5 轮，ACM 省赛银牌 \\
\end{tabularx}

\end{document}
"""

# ---------------------------------------------------------------------------
# 简历存取
# ---------------------------------------------------------------------------


def save_resume(content: str):
    """保存用户简历内容。"""
    RESUME_FILE.write_text(content, encoding="utf-8")


def load_resume() -> str:
    """加载用户简历内容。"""
    if RESUME_FILE.exists():
        return RESUME_FILE.read_text(encoding="utf-8")
    return ""


def save_analysis(analysis: dict):
    """保存分析结果。"""
    RESUME_ANALYSIS_FILE.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")


def load_analysis() -> dict:
    """加载分析结果。"""
    if RESUME_ANALYSIS_FILE.exists():
        try:
            return json.loads(RESUME_ANALYSIS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            pass
    return {}


# ---------------------------------------------------------------------------
# 简历对话历史
# ---------------------------------------------------------------------------

_MAX_RESUME_HISTORY = 30


def load_resume_chat() -> list:
    if not RESUME_CHAT_FILE.exists():
        return []
    try:
        data = json.loads(RESUME_CHAT_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def save_resume_chat(history: list):
    from .memory import compress_history
    compressed = compress_history(history)
    trimmed = compressed[-_MAX_RESUME_HISTORY * 2:]
    RESUME_CHAT_FILE.write_text(
        json.dumps(trimmed, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_resume_chat():
    if RESUME_CHAT_FILE.exists():
        RESUME_CHAT_FILE.unlink()


# ---------------------------------------------------------------------------
# AI 分析
# ---------------------------------------------------------------------------

_ANALYSIS_SYSTEM = """你是一位资深技术招聘专家和简历顾问，擅长帮助程序员优化简历。

请从以下维度分析这份简历，给出具体、可操作的建议：

### 整体评分（满分 100）
给出一个总分和简短评语。

### 内容分析
1. **个人信息**：联系方式是否完整、专业
2. **教育背景**：是否突出了相关课程和成绩
3. **工作/实习经历**：是否用 STAR 法则描述，是否量化了成果
4. **项目经历**：是否体现技术深度和解决问题能力
5. **技能清单**：是否与目标岗位匹配，排列是否合理

### 格式与排版
- 长度是否合适（建议 1 页）
- 要点是否精炼（每条 1-2 行）
- 是否有拼写/语法错误

### 亮点
列出 2-3 个简历中做得好的地方。

### 改进建议
按优先级列出 3-5 条具体的改进建议，每条说明：
- 当前问题
- 修改方向
- 修改示例（如适用）

请用中文回答，简洁专业。"""

_CHAT_SYSTEM = """你是一位资深技术招聘专家和简历顾问。用户正在优化他们的简历，请帮助他们改进。

用户当前的简历内容：
---
{resume}
---

{analysis_context}

请根据用户的问题给出具体、可操作的建议。如果用户要求修改某部分内容，请直接给出修改后的文字。用中文回答。"""


def analyze_resume(content: str) -> Optional[str]:
    """AI 分析简历，返回分析文本。"""
    ai_config = get_ai_config()
    if not ai_config["enabled"]:
        return None

    messages = [{"role": "user", "content": f"请分析以下简历：\n\n{content}"}]
    return call_ai_messages(messages, ai_config, system=_ANALYSIS_SYSTEM)


def chat_resume(user_message: str, history: list,
                resume_content: str, analysis_text: str = "") -> Optional[str]:
    """简历优化对话。自动注入共享记忆。"""
    ai_config = get_ai_config()
    if not ai_config["enabled"]:
        return None

    from .memory import format_memory_for_prompt, extract_and_save_memory

    analysis_ctx = ""
    if analysis_text:
        analysis_ctx = f"之前的 AI 分析结果：\n{analysis_text[:2000]}"

    system = _CHAT_SYSTEM.format(
        resume=resume_content[:4000],
        analysis_context=analysis_ctx,
    )
    memory_text = format_memory_for_prompt()
    if memory_text:
        system += memory_text

    messages = list(history)
    messages.append({"role": "user", "content": user_message})
    reply = call_ai_messages(messages, ai_config, system=system)

    if reply:
        try:
            extract_and_save_memory(user_message, reply, source="简历优化")
        except Exception:
            pass

    return reply


# ---------------------------------------------------------------------------
# 面试题生成 & 模拟面试
# ---------------------------------------------------------------------------

INTERVIEW_FILE = DATA_DIR / "interview_questions.json"
INTERVIEW_CHAT_FILE = DATA_DIR / "interview_chat_history.json"

_INTERVIEW_GEN_SYSTEM = """你是一位资深技术面试官。请根据候选人的简历，生成一份有针对性的面试题清单。

要求：
1. 题目必须紧扣简历中的项目经历、技术栈和工作内容
2. 按类别分组，每组 3-5 题
3. 标注难度（基础 / 进阶 / 深挖）
4. 包含以下类别：
   - **项目深挖**：针对简历中每个项目的细节追问
   - **技术原理**：考察简历中提到的核心技术的底层原理
   - **系统设计**：基于简历经验出的设计题
   - **算法编程**：与简历技术栈相关的算法题
   - **行为面试**：团队协作、挑战、成长类问题

请按以下 Markdown 格式输出：

## 项目深挖
1. **[基础]** 题目内容
2. **[进阶]** 题目内容
...

## 技术原理
...

用中文回答。"""

_MOCK_INTERVIEW_SYSTEM = """你是一位严格但友善的技术面试官，正在面试候选人。

候选人的简历：
---
{resume}
---

面试规则：
1. 每次只问一个问题，等候选人回答后再继续
2. 根据候选人的回答进行追问，不断深挖
3. 如果回答不够好，给出提示引导，不要直接给答案
4. 如果回答得好，给予肯定并过渡到下一个问题
5. 结合简历中的项目和技术栈来提问
6. 适当穿插基础原理、系统设计、行为面试等不同类型的问题
7. 保持对话自然流畅，像真实面试一样

现在开始面试。先简短自我介绍（一句话），然后提出第一个问题。"""


def generate_interview_questions(resume_content: str) -> Optional[str]:
    """根据简历生成面试题列表。"""
    ai_config = get_ai_config()
    if not ai_config["enabled"]:
        return None

    messages = [{"role": "user", "content": f"请根据以下简历生成面试题：\n\n{resume_content}"}]
    result = call_ai_messages(messages, ai_config, system=_INTERVIEW_GEN_SYSTEM)
    if result:
        INTERVIEW_FILE.write_text(
            json.dumps({"questions": result}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    return result


def load_interview_questions() -> str:
    if INTERVIEW_FILE.exists():
        try:
            data = json.loads(INTERVIEW_FILE.read_text(encoding="utf-8"))
            return data.get("questions", "")
        except (json.JSONDecodeError, IOError):
            pass
    return ""


def load_interview_chat() -> list:
    if not INTERVIEW_CHAT_FILE.exists():
        return []
    try:
        data = json.loads(INTERVIEW_CHAT_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def save_interview_chat(history: list):
    from .memory import compress_history
    compressed = compress_history(history)
    trimmed = compressed[-60:]
    INTERVIEW_CHAT_FILE.write_text(
        json.dumps(trimmed, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_interview_chat():
    if INTERVIEW_CHAT_FILE.exists():
        INTERVIEW_CHAT_FILE.unlink()


def chat_interview(user_message: str, history: list,
                   resume_content: str) -> Optional[str]:
    """模拟面试对话。自动注入共享记忆。"""
    ai_config = get_ai_config()
    if not ai_config["enabled"]:
        return None

    from .memory import format_memory_for_prompt, extract_and_save_memory

    system = _MOCK_INTERVIEW_SYSTEM.format(resume=resume_content[:4000])
    memory_text = format_memory_for_prompt()
    if memory_text:
        system += memory_text

    messages = list(history)
    messages.append({"role": "user", "content": user_message})
    reply = call_ai_messages(messages, ai_config, system=system)

    if reply:
        try:
            extract_and_save_memory(user_message, reply, source="模拟面试")
        except Exception:
            pass

    return reply
