"""本地 Web 看板：启动 HTTP 服务，展示完整刷题数据。

替代桌面 Markdown 文件，提供交互式 Web 界面查看所有刷题信息：
- 数据概览 Dashboard
- 100 题进度表（筛选 / 搜索）
- 每日打卡时间线
- 代码优化建议
"""

from __future__ import annotations

import json
import re
import threading
import webbrowser
from datetime import date
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Optional

from .storage import load_json, save_json, save_text
from .features import ROUND_KEYS, compute_category_stats
from .config import DATA_DIR, load_plan_config, save_plan_config, load_push_config, save_push_config
from datetime import timedelta
from .init_plan import SLUG_CATEGORY

# Avoid concurrent browser-login flows from duplicate clicks or repeated requests.
_LOGIN_LOCK = threading.Lock()
_LOGIN_RUNNING = False
_TODAY_FOCUS_FILE = DATA_DIR / "today_focus.json"
_TODAY_FOCUS_COUNT = 5

# ---------------------------------------------------------------------------
# 数据构建
# ---------------------------------------------------------------------------


def _load_today_focus_state() -> dict:
    return load_json(_TODAY_FOCUS_FILE, default={})


def _save_today_focus_state(state: dict):
    save_json(_TODAY_FOCUS_FILE, state)


def _pick_today_focus(
    todos: list[dict],
    desired_count: int,
    keep_slugs: list[str] | None = None,
    preferred_category: str = "",
) -> tuple[list[dict], str]:
    """Prefer one category, while keeping today's unfinished picks stable."""
    keep_slugs = keep_slugs or []
    todo_by_slug = {item["slug"]: item for item in todos}
    selected = [todo_by_slug[slug] for slug in keep_slugs if slug in todo_by_slug]
    selected_slugs = {item["slug"] for item in selected}

    grouped: dict[str, list[dict]] = {}
    ordered_categories: list[str] = []
    for item in todos:
        cat = item["category"]
        if cat not in grouped:
            grouped[cat] = []
            ordered_categories.append(cat)
        grouped[cat].append(item)

    if not preferred_category or preferred_category not in grouped:
        if selected:
            preferred_category = selected[0]["category"]
        else:
            for cat in ordered_categories:
                if len(grouped[cat]) >= desired_count:
                    preferred_category = cat
                    break
            if not preferred_category and ordered_categories:
                order_index = {cat: idx for idx, cat in enumerate(ordered_categories)}
                preferred_category = max(
                    ordered_categories,
                    key=lambda cat: (len(grouped[cat]), -order_index[cat]),
                )

    if preferred_category in grouped:
        for item in grouped[preferred_category]:
            if item["slug"] in selected_slugs:
                continue
            selected.append(item)
            selected_slugs.add(item["slug"])
            if len(selected) >= desired_count:
                return selected[:desired_count], preferred_category

    for item in todos:
        if item["slug"] in selected_slugs:
            continue
        selected.append(item)
        selected_slugs.add(item["slug"])
        if len(selected) >= desired_count:
            break

    return selected[:desired_count], preferred_category


def _build_today_focus(todos: list[dict], desired_count: int) -> tuple[list[dict], str]:
    today_str = date.today().isoformat()
    config = load_plan_config()
    state = _load_today_focus_state()
    keep_slugs: list[str] = []
    preferred_category = ""

    if (
        state.get("date") == today_str
        and state.get("problem_list") == config.get("problem_list", "hot100")
    ):
        keep_slugs = state.get("slugs", [])
        preferred_category = state.get("preferred_category", "")

    focus_items, preferred_category = _pick_today_focus(
        todos, desired_count, keep_slugs, preferred_category,
    )
    _save_today_focus_state({
        "date": today_str,
        "problem_list": config.get("problem_list", "hot100"),
        "preferred_category": preferred_category,
        "slugs": [item["slug"] for item in focus_items],
    })
    return focus_items, preferred_category


def _compute_trends(checkin_data: list) -> dict:
    """计算周/月趋势统计。"""
    if not checkin_data:
        return {"this_week": 0, "last_week": 0, "this_month": 0, "last_month": 0,
                "avg_daily": 0, "week_change": 0}
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    last_week_start = week_start - timedelta(days=7)
    month_start = today.replace(day=1)
    if month_start.month == 1:
        last_month_start = month_start.replace(year=month_start.year - 1, month=12)
    else:
        last_month_start = month_start.replace(month=month_start.month - 1)

    tw = sum(e["total"] for e in checkin_data if e["date"] >= week_start)
    lw = sum(e["total"] for e in checkin_data if last_week_start <= e["date"] < week_start)
    tm = sum(e["total"] for e in checkin_data if e["date"] >= month_start)
    lm = sum(e["total"] for e in checkin_data if last_month_start <= e["date"] < month_start)

    recent_30 = [e for e in checkin_data if e["date"] >= today - timedelta(days=30)]
    avg = sum(e["total"] for e in recent_30) / max(len(recent_30), 1)
    change = ((tw - lw) / max(lw, 1) * 100) if lw > 0 else 0

    return {
        "this_week": tw, "last_week": lw,
        "this_month": tm, "last_month": lm,
        "avg_daily": round(avg, 1),
        "week_change": round(change),
    }


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
    from .problem_data import get_all_problem_data
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
    today_str = date.today().isoformat()
    today_ac = sum(
        1 for row in rows
        if any((row.get(rk) or "").strip() == today_str for rk in ROUND_KEYS)
    )

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

    # R1 未做的新题 — 按分类分组，优先推荐薄弱分类，同一分类的题集中推荐
    cat_stats = compute_category_stats(rows)
    raw_todo = []
    for row in rows:
        if row["r1"] and row["r1"] not in ("", "—"):
            continue
        title_match = re.search(r"\[(.+?)\]", row["title"])
        display_title = title_match.group(1) if title_match else row["title"]
        cat = SLUG_CATEGORY.get(row.get("title_slug", ""), "其他")
        raw_todo.append({
            "title": display_title,
            "slug": row.get("title_slug", ""),
            "difficulty": row["difficulty"],
            "category": cat,
        })

    # 按分类完成率排序（低完成率优先），同分类内按简单→困难
    diff_order = {"简单": 0, "中等": 1, "困难": 2}
    def _cat_priority(cat_name):
        cs = cat_stats.get(cat_name, {})
        total = cs.get("total", 1)
        done = cs.get("done_r1", 0)
        return done / max(total, 1)  # 完成率越低越优先

    # 先按分类分组（薄弱分类排前面），组内按简单→困难
    from collections import OrderedDict
    sorted_cats = sorted(set(t["category"] for t in raw_todo), key=_cat_priority)
    cat_groups = OrderedDict((c, []) for c in sorted_cats)
    for t in raw_todo:
        cat_groups[t["category"]].append(t)
    for items in cat_groups.values():
        items.sort(key=lambda x: diff_order.get(x["difficulty"], 1))
    new_todo = []
    for items in cat_groups.values():
        new_todo.extend(items)
    today_focus, today_focus_category = _build_today_focus(new_todo, _TODAY_FOCUS_COUNT)

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
        "started_problems": stats["per_round"].get("r1", 0),
        "total_rounds": stats["total_rounds"],
        "done_rounds": stats["done_rounds"],
        "done_problems": stats["done_problems"],
        "today_ac": today_ac,
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
        "today_focus": today_focus,
        "today_focus_category": today_focus_category,
        "today_focus_target": _TODAY_FOCUS_COUNT,
        "plan_config": load_plan_config(),
        "ai_usage": __import__('leetcode_auto.ai_analyzer', fromlist=['get_ai_usage']).get_ai_usage(),
        "user_profile": __import__('leetcode_auto.leetcode_api', fromlist=['load_user_profile']).load_user_profile(),
        "struggles": __import__('leetcode_auto.leetcode_api', fromlist=['load_struggle_notebook']).load_struggle_notebook(),
        "push_config": {k: v for k, v in load_push_config().items() if k != "smtp_pass"},
        "trend_stats": _compute_trends(checkin_data),
        "available_lists": {k: {"name": v["name"], "name_en": v["name_en"], "count": len(v["problems"])} for k, v in __import__('leetcode_auto.problem_lists', fromlist=['PROBLEM_LISTS']).PROBLEM_LISTS.items()},
        "problem_data": get_all_problem_data(),
        "optimizations": optimizations,
    }


# ---------------------------------------------------------------------------
# HTML 模板（从 web_template.py 加载）
# ---------------------------------------------------------------------------

from .web_template import _HTML_TEMPLATE



# ---------------------------------------------------------------------------
# HTTP 服务
# ---------------------------------------------------------------------------


def _reload_data() -> dict:
    """从文件重新读取所有数据，供 /api/data 实时返回最新状态。"""
    from .progress import (
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

    def _render_html() -> bytes:
        """每次请求时重新生成 HTML（配置变更后立即生效）。"""
        fresh = _reload_data()
        today_str = date.today().strftime("%Y-%m-%d")
        s = fresh
        streak_class = "fire" if s.get("streak", 0) >= 3 else ""
        html = _HTML_TEMPLATE
        html = html.replace("__DATA_JSON__", json.dumps(fresh, ensure_ascii=False))
        html = html.replace("__DONE_ROUNDS__", str(s["done_rounds"]))
        html = html.replace("__TOTAL_ROUNDS__", str(s["total_rounds"]))
        html = html.replace("__RATE__", f"{s['rate']:.1f}")
        html = html.replace("__TODAY_AC__", str(s.get("today_ac", 0)))
        html = html.replace("__DONE_ALL__", str(s["done_problems"]))
        html = html.replace("__TOTAL__", str(s["total"]))
        html = html.replace("__STREAK__", str(s["streak"]))
        html = html.replace("__STREAK_CLASS__", streak_class)
        html = html.replace("__TOTAL_DAYS__", str(s["total_days"]))
        html = html.replace("__EST__", str(s["est"]))
        html = html.replace("__TODAY__", today_str)
        return html.encode("utf-8")

    class Handler(SimpleHTTPRequestHandler):
        def _send_json(self, data: dict, status: int = 200):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return {}

        def _start_login(self):
            global _LOGIN_RUNNING
            from .leetcode_api import browser_login

            with _LOGIN_LOCK:
                if _LOGIN_RUNNING:
                    self._send_json({"status": "running"})
                    return
                _LOGIN_RUNNING = True

            def _do_login():
                global _LOGIN_RUNNING
                try:
                    browser_login()
                    from .sync import sync
                    sync(interactive=False)
                except Exception as e:
                    print(f"Login failed: {e}")
                finally:
                    with _LOGIN_LOCK:
                        _LOGIN_RUNNING = False

            threading.Thread(target=_do_login, daemon=True).start()
            self._send_json({"status": "started"})

        def _start_sync(self):
            def _do_sync():
                try:
                    from .sync import sync
                    sync(interactive=False)
                except Exception as e:
                    print(f"Sync failed: {e}")

            threading.Thread(target=_do_sync, daemon=True).start()
            self._send_json({"status": "started"})

        # --- GET 路由处理 ---

        def _get_chat_history(self):
            from .ai_analyzer import load_chat_history
            self._send_json({"history": load_chat_history()})

        def _get_resume_template(self):
            from .resume import RESUME_TEMPLATE
            body = RESUME_TEMPLATE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=resume_template.md")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _get_resume(self):
            from .resume import load_resume, load_analysis, load_resume_chat, get_resume_list
            self._send_json({
                "content": load_resume(),
                "analysis": load_analysis().get("text", ""),
                "chat_history": load_resume_chat(),
                "resume_list": get_resume_list(),
            })

        def _get_interview(self):
            from .resume import load_interview_questions, load_interview_chat, load_interview_report
            self._send_json({
                "questions": load_interview_questions(),
                "chat_history": load_interview_chat(),
                "report": load_interview_report(),
            })

        def _get_logout(self):
            from .config import COOKIES_FILE, DATA_DIR
            if COOKIES_FILE.exists():
                COOKIES_FILE.unlink()
            pf = DATA_DIR / "user_profile.json"
            if pf.exists():
                pf.unlink()
            self._send_json({"ok": True})

        def _get_data(self):
            self._send_json(_reload_data())

        _GET_ROUTES = {  # login/sync 同时支持 GET 和 POST 以兼容前端不同调用方式
            "/api/chat/history": "_get_chat_history",
            "/api/resume/template": "_get_resume_template",
            "/api/resume": "_get_resume",
            "/api/interview": "_get_interview",
            "/api/logout": "_get_logout",
            "/api/sync": "_start_sync",
            "/api/login": "_start_login",
            "/api/data": "_get_data",
        }

        def do_GET(self):
            handler_name = self._GET_ROUTES.get(self.path)
            if handler_name:
                getattr(self, handler_name)()
            else:
                page = _render_html()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)

        # --- POST 路由处理 ---

        def _post_chat(self):
            req = self._read_json()
            msg = req.get("message", "")
            history = req.get("history", [])
            from .config import get_ai_config
            ai_config = get_ai_config()
            if not ai_config["enabled"]:
                self._send_json({"error": "AI 未配置，请在 ~/.leetcode_auto/.env 中设置 AI_PROVIDER 和 AI_API_KEY"})
                return
            from .ai_analyzer import (
                build_chat_context, chat as ai_chat,
                save_chat_history, get_last_ai_error,
            )
            system_prompt = build_chat_context()
            reply = ai_chat(msg, history, system_prompt)
            if reply:
                history.append({"role": "user", "content": msg})
                history.append({"role": "assistant", "content": reply})
                save_chat_history(history)
                self._send_json({"reply": reply})
            else:
                self._send_json({"error": get_last_ai_error() or "AI 请求失败，请重试"})

        def _post_chat_history(self):
            req = self._read_json()
            if req.get("action") == "clear":
                from .ai_analyzer import clear_chat_history
                clear_chat_history()
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "unknown action"})

        def _post_problem(self):
            req = self._read_json()
            action = req.get("action", "")
            from .problem_data import save_note, add_time_spent, set_solution_viewed, set_must_repeat
            if action == "save_note":
                save_note(req.get("slug", ""), req.get("note", ""))
            elif action == "add_time":
                add_time_spent(req.get("slug", ""), req.get("seconds", 0))
            elif action == "set_solution_viewed":
                set_solution_viewed(req.get("slug", ""), req.get("viewed", False))
            elif action == "set_must_repeat":
                set_must_repeat(req.get("slug", ""), req.get("repeat", False))
            else:
                self._send_json({"error": "unknown"})
                return
            self._send_json({"ok": True})

        def _post_today_focus(self):
            req = self._read_json()
            if req.get("action") != "check_done":
                self._send_json({"error": "unknown"})
                return
            slug = req.get("slug", "")
            try:
                from .sync import sync
                sync(interactive=False)
                fresh = _reload_data()
                today_str = date.today().isoformat()
                row = next((r for r in fresh.get("rows", []) if r.get("slug") == slug), None)
                completed_today = bool(row and (row.get("r1") or "").strip() == today_str)
                result = {"ok": True, "completed_today": completed_today, "today_focus": fresh.get("today_focus", [])}
                if not completed_today:
                    result["message"] = "今天还没检测到这道题的新一轮完成记录。"
                self._send_json(result)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)})

        def _post_push_config(self):
            req = self._read_json()
            action = req.get("action", "save")
            if action == "save":
                save_push_config(req.get("config", {}))
                self._send_json({"ok": True})
            elif action == "test":
                from .features import push_report
                push_report("BrushUp Test: If you see this, push is working!")
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "unknown"})

        def _post_settings(self):
            req = self._read_json()
            old_cfg = load_plan_config()
            new_list = req.get("problem_list", "hot100")
            old_list = old_cfg.get("problem_list", "hot100")
            save_plan_config(req)
            if new_list != old_list:
                from .problem_lists import get_problem_list
                from .init_plan import _gen_progress_table
                from .config import PROGRESS_FILE, PLAN_DIR
                import shutil
                backup = PLAN_DIR / f"01_进度表_{old_list}.md"
                if PROGRESS_FILE.exists() and not backup.exists():
                    shutil.copy2(PROGRESS_FILE, backup)
                restore = PLAN_DIR / f"01_进度表_{new_list}.md"
                if restore.exists():
                    shutil.copy2(restore, PROGRESS_FILE)
                else:
                    problems = get_problem_list(new_list)
                    save_text(PROGRESS_FILE, _gen_progress_table(problems))
            self._send_json({"ok": True})

        def _post_interview(self):
            req = self._read_json()
            action = req.get("action", "")
            from .resume import (
                load_resume, generate_interview_questions,
                chat_interview, save_interview_chat, clear_interview_chat,
            )
            from .ai_analyzer import get_last_ai_error
            if action == "generate":
                content = req.get("content", "")
                from .resume import save_resume as _sr
                _sr(content)
                questions = generate_interview_questions(content)
                result = {"questions": questions} if questions else {"error": get_last_ai_error() or "AI 未配置或请求失败"}
            elif action == "start":
                resume_content = load_resume()
                if not resume_content:
                    result = {"error": "请先粘贴简历内容"}
                else:
                    reply = chat_interview("请开始面试", [], resume_content)
                    if reply:
                        save_interview_chat([{"role": "assistant", "content": reply}])
                        result = {"reply": reply}
                    else:
                        result = {"error": get_last_ai_error() or "AI 未配置或请求失败"}
            elif action == "chat":
                msg = req.get("message", "")
                history = req.get("history", [])
                resume_content = load_resume()
                reply = chat_interview(msg, history, resume_content)
                if reply:
                    history.append({"role": "user", "content": msg})
                    history.append({"role": "assistant", "content": reply})
                    save_interview_chat(history)
                    result = {"reply": reply}
                else:
                    result = {"error": get_last_ai_error() or "AI 未配置或请求失败"}
            elif action == "clear":
                clear_interview_chat()
                result = {"ok": True}
            elif action == "report":
                from .resume import generate_interview_report, load_interview_chat as _lic
                hist = _lic()
                report = generate_interview_report(hist)
                result = {"report": report} if report else {"error": "AI 未配置或对话为空"}
            else:
                result = {"error": "未知操作"}
            self._send_json(result)

        def _post_resume(self):
            req = self._read_json()
            action = req.get("action", "")
            from .resume import (
                save_resume, load_resume, analyze_resume,
                save_analysis, load_analysis,
                chat_resume, save_resume_chat, clear_resume_chat,
            )
            from .ai_analyzer import get_last_ai_error
            if action == "save":
                save_resume(req.get("content", ""))
                result = {"ok": True}
            elif action == "analyze":
                content = req.get("content", "")
                save_resume(content)
                analysis = analyze_resume(content)
                if analysis:
                    save_analysis({"text": analysis})
                    result = {"analysis": analysis}
                else:
                    result = {"error": get_last_ai_error() or "AI not configured or request failed"}
            elif action == "chat":
                msg = req.get("message", "")
                history = req.get("history", [])
                resume_content = req.get("content") or load_resume()
                if req.get("content"):
                    save_resume(req["content"])
                analysis_text = load_analysis().get("text", "")
                reply = chat_resume(msg, history, resume_content, analysis_text)
                if reply:
                    history.append({"role": "user", "content": msg})
                    history.append({"role": "assistant", "content": reply})
                    save_resume_chat(history)
                    result = {"reply": reply}
                else:
                    result = {"error": get_last_ai_error() or "AI not configured or request failed"}
            elif action == "clear_chat":
                clear_resume_chat()
                result = {"ok": True}
            elif action == "switch_resume":
                from .resume import switch_resume
                switch_resume(req.get("resume_id", "default"))
                result = {"ok": True}
            elif action == "create_resume":
                from .resume import create_resume
                new_id = create_resume(req.get("name", "新简历"))
                result = {"ok": True, "id": new_id}
            elif action == "delete_resume":
                from .resume import delete_resume
                delete_resume(req.get("resume_id", ""))
                result = {"ok": True}
            elif action == "rename_resume":
                from .resume import rename_resume
                rename_resume(req.get("resume_id", ""), req.get("name", ""))
                result = {"ok": True}
            elif action == "list_versions":
                from .resume import get_resume_versions
                result = {"versions": get_resume_versions()}
            elif action == "restore_version":
                from .resume import restore_resume_version
                content = restore_resume_version(req.get("file", ""))
                result = {"ok": True, "content": content}
            else:
                result = {"error": "unknown action"}
            self._send_json(result)

        _POST_ROUTES = {
            "/api/login": "_start_login",
            "/api/logout": "_get_logout",
            "/api/sync": "_start_sync",
            "/api/chat": "_post_chat",
            "/api/chat/history": "_post_chat_history",
            "/api/problem": "_post_problem",
            "/api/today-focus": "_post_today_focus",
            "/api/push-config": "_post_push_config",
            "/api/settings": "_post_settings",
            "/api/interview": "_post_interview",
            "/api/resume": "_post_resume",
        }

        def do_POST(self):
            handler_name = self._POST_ROUTES.get(self.path)
            if handler_name:
                getattr(self, handler_name)()
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
