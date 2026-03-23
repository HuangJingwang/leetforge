"""LeetCode API interactions: session checks, submission fetching, and optimization analysis."""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

from .config import LEETCODE_API_URL, COOKIES_FILE, load_credentials

CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# 0. 登录状态检测 & 浏览器登录
# ---------------------------------------------------------------------------


class SessionCheckResult:
    """区分"Cookie 过期"和"网络错误"。"""
    def __init__(self, username: Optional[str] = None,
                 expired: bool = False, network_error: bool = False):
        self.username = username
        self.expired = expired
        self.network_error = network_error


def check_session(session: str, csrf: str) -> SessionCheckResult:
    """检查当前 Cookie 是否有效。返回 SessionCheckResult 区分三种情况。"""
    if not session:
        return SessionCheckResult(expired=True)
    query = """
    query globalData {
        userStatus {
            isSignedIn
            userSlug
            username
        }
    }
    """
    headers = {
        "Content-Type": "application/json",
        "Referer": "https://leetcode.cn",
        "Cookie": f"LEETCODE_SESSION={session}; csrftoken={csrf}",
        "x-csrftoken": csrf,
    }
    try:
        resp = requests.post(
            LEETCODE_API_URL, json={"query": query}, headers=headers, timeout=10,
        )
        data = resp.json()
        us = data.get("data", {}).get("userStatus", {})
        if us.get("isSignedIn"):
            slug = us.get("userSlug") or us.get("username")
            return SessionCheckResult(username=slug)
        return SessionCheckResult(expired=True)
    except Exception:
        return SessionCheckResult(network_error=True)


def _ensure_chromium():
    """检查 Chromium 是否已安装，未安装则自动下载。"""
    from pathlib import Path
    cache_dir = Path.home() / "Library" / "Caches" / "ms-playwright"
    if not cache_dir.exists():
        cache_dir = Path.home() / ".cache" / "ms-playwright"
    has_chromium = any(cache_dir.glob("chromium-*/")) if cache_dir.exists() else False
    if not has_chromium:
        print("正在安装 Chromium 浏览器引擎（仅首次需要）...")
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
        print()


def browser_login() -> dict:
    """打开浏览器登录 LeetCode CN，返回凭证字典。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("错误：请先安装 playwright")
        print("  pip install playwright")
        sys.exit(1)

    print("正在启动浏览器...\n", flush=True)

    stealth_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=False, channel="chrome", args=stealth_args)
        except Exception:
            _ensure_chromium()
            browser = p.chromium.launch(headless=False, args=stealth_args)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            window.chrome = { runtime: {} };
        """)
        page = context.new_page()
        page.goto("https://leetcode.cn/accounts/login/")

        print("请在浏览器中完成登录（支持账号密码、微信、GitHub、QQ 等方式）", flush=True)
        print("登录成功后会自动检测，无需手动操作...\n", flush=True)

        import time as _time
        deadline = _time.time() + 300
        session_val = ""
        csrf_val = ""
        while _time.time() < deadline:
            try:
                for c in context.cookies("https://leetcode.cn"):
                    if c["name"] == "LEETCODE_SESSION":
                        session_val = c["value"]
                    elif c["name"] == "csrftoken":
                        csrf_val = c["value"]
            except Exception:
                pass
            if session_val:
                page.wait_for_timeout(1000)
                break
            page.wait_for_timeout(1500)

        if not session_val:
            print("超时（5 分钟内未检测到登录），请重试。", flush=True)
            browser.close()
            sys.exit(1)

        browser.close()

    if not session_val:
        print("未检测到 LEETCODE_SESSION Cookie，登录可能未成功，请重试。", flush=True)
        sys.exit(1)

    result = check_session(session_val, csrf_val)
    username = result.username or "unknown"
    data = {
        "username": username,
        "LEETCODE_SESSION": session_val,
        "csrftoken": csrf_val,
        "saved_at": datetime.now(CST).isoformat(),
    }
    COOKIES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"登录成功！用户：{username}", flush=True)
    print(f"Cookie 已保存到 {COOKIES_FILE}\n", flush=True)
    return {"username": username, "session": session_val, "csrf": csrf_val}


def ensure_credentials(interactive: bool = True) -> dict:
    """加载并验证凭证。interactive=False 时不弹浏览器，凭证失效则返回空。"""
    creds = load_credentials()
    if creds["session"]:
        print("正在检查登录状态...", flush=True)
        result = check_session(creds["session"], creds["csrf"])
        if result.username:
            print(f"已登录：{result.username}\n", flush=True)
            creds["username"] = result.username
            return creds
        if result.network_error:
            print("网络连接失败，跳过登录检查，使用缓存凭证继续。\n", flush=True)
            return creds
        if not interactive:
            print("Cookie 已过期，请手动运行 leetcode --login 重新登录。", flush=True)
            return {}
        print("Cookie 已过期，需要重新登录。\n", flush=True)
    else:
        if not interactive:
            print("未找到登录凭证，请手动运行 leetcode --login 登录。", flush=True)
            return {}
        print("未找到登录凭证，需要登录。\n", flush=True)
    return browser_login()


# ---------------------------------------------------------------------------
# 1. LeetCode API
# ---------------------------------------------------------------------------

SUBMISSION_LIST_QUERY = """
query submissionList($offset: Int!, $limit: Int!, $questionSlug: String!) {
    submissionList(offset: $offset, limit: $limit, questionSlug: $questionSlug) {
        hasNext
        submissions {
            id
            title
            statusDisplay
            timestamp
            url
        }
    }
}
"""


def _make_headers(session: str, csrf: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Referer": "https://leetcode.cn",
        "Cookie": f"LEETCODE_SESSION={session}; csrftoken={csrf}",
        "x-csrftoken": csrf,
    }


def _fetch_submission_list(session: str, csrf: str, limit: int = 80) -> list[dict]:
    """拉取最近提交列表，从 url 字段解析 titleSlug。"""
    headers = _make_headers(session, csrf)
    payload = {
        "query": SUBMISSION_LIST_QUERY,
        "variables": {"offset": 0, "limit": limit, "questionSlug": ""},
    }
    resp = requests.post(LEETCODE_API_URL, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"LeetCode API 返回错误: {data['errors']}")
    subs = data.get("data", {}).get("submissionList", {}).get("submissions") or []
    for s in subs:
        m = re.search(r"/problems/([^/]+)/submissions/", s.get("url", ""))
        s["titleSlug"] = m.group(1) if m else ""
    return subs


def fetch_recent_ac(username: str, session: str, csrf: str, limit: int = 80) -> list[dict]:
    subs = _fetch_submission_list(session, csrf, limit)
    return [s for s in subs if s.get("statusDisplay") == "Accepted"]


def fetch_recent_all(username: str, session: str, csrf: str) -> list[dict]:
    """拉取最近的所有提交（含失败），用于卡点检测。失败时返回空列表。"""
    try:
        return _fetch_submission_list(session, csrf, limit=80)
    except Exception:
        return []


SUBMISSION_DETAIL_QUERY = """
query submissionDetail($submissionId: ID!) {
    submissionDetail(submissionId: $submissionId) {
        id
        code
        runtime
        memory
        runtimePercentile
        memoryPercentile
        lang {
            name
        }
        question {
            titleSlug
            title
            translatedTitle
        }
    }
}
"""


def fetch_submission_detail(session: str, csrf: str, submission_id: str) -> dict:
    """获取单个提交的详细信息（代码、运行时间/内存百分位等）。"""
    headers = _make_headers(session, csrf)
    payload = {
        "query": SUBMISSION_DETAIL_QUERY,
        "variables": {"submissionId": submission_id},
    }
    resp = requests.post(LEETCODE_API_URL, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", {}).get("submissionDetail", {}) or {}


def check_optimization_potential(detail: dict, threshold: float = 50.0) -> Optional[dict]:
    """检查提交是否有优化空间。

    threshold: 百分位阈值，低于此值认为有优化空间（默认 50%）。
    返回优化建议字典，无优化空间返回 None。
    """
    if not detail:
        return None

    runtime_pct = detail.get("runtimePercentile")
    memory_pct = detail.get("memoryPercentile")

    if runtime_pct is None and memory_pct is None:
        return None

    suggestions = []
    runtime_pct = float(runtime_pct) if runtime_pct is not None else None
    memory_pct = float(memory_pct) if memory_pct is not None else None

    if runtime_pct is not None and runtime_pct < threshold:
        suggestions.append(f"运行时间击败 {runtime_pct:.1f}% 用户，建议优化时间复杂度")
    if memory_pct is not None and memory_pct < threshold:
        suggestions.append(f"内存使用击败 {memory_pct:.1f}% 用户，建议优化空间复杂度")

    if not suggestions:
        return None

    question = detail.get("question", {})
    return {
        "title_slug": question.get("titleSlug", ""),
        "title": question.get("translatedTitle") or question.get("title", ""),
        "lang": detail.get("lang", {}).get("name", ""),
        "runtime": detail.get("runtime", ""),
        "memory": detail.get("memory", ""),
        "runtime_pct": runtime_pct,
        "memory_pct": memory_pct,
        "code": detail.get("code", ""),
        "suggestions": suggestions,
    }


def analyze_submissions_for_optimization(
    session: str, csrf: str, today_subs: list[dict], threshold: float = 50.0,
) -> list[dict]:
    """批量分析今日 AC 提交的优化空间。"""
    results = []
    for sub in today_subs:
        sub_id = sub.get("id")
        if not sub_id:
            continue
        try:
            detail = fetch_submission_detail(session, csrf, str(sub_id))
            opt = check_optimization_potential(detail, threshold)
            if opt:
                results.append(opt)
        except Exception:
            continue
    return results


def filter_today_ac(submissions: list[dict]) -> list[dict]:
    today_start = datetime.now(CST).replace(hour=0, minute=0, second=0, microsecond=0)
    seen: set[str] = set()
    result: list[dict] = []
    for sub in submissions:
        ts = datetime.fromtimestamp(int(sub["timestamp"]), tz=CST)
        if ts >= today_start and sub["titleSlug"] not in seen:
            seen.add(sub["titleSlug"])
            result.append(sub)
    return result


def detect_struggles(all_subs: list[dict], ac_slugs: set[str]) -> list[str]:
    """检测今日多次提交才 AC 的题目（>=3 次尝试），返回题名列表。"""
    today_start = datetime.now(CST).replace(hour=0, minute=0, second=0, microsecond=0)
    attempt_count: dict[str, int] = {}
    slug_to_title: dict[str, str] = {}
    for sub in all_subs:
        ts = datetime.fromtimestamp(int(sub["timestamp"]), tz=CST)
        if ts < today_start:
            continue
        slug = sub["titleSlug"]
        attempt_count[slug] = attempt_count.get(slug, 0) + 1
        slug_to_title[slug] = sub.get("title", slug)
    return [
        slug_to_title[slug]
        for slug in ac_slugs
        if attempt_count.get(slug, 0) >= 3
    ]
