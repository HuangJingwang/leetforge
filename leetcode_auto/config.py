import json
import os
from pathlib import Path

from dotenv import load_dotenv

DATA_DIR = Path(os.getenv("LEETCODE_AUTO_DIR", os.path.expanduser("~/.leetcode_auto")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(DATA_DIR / ".env")

LEETCODE_API_URL = "https://leetcode.cn/graphql/"
COOKIES_FILE = DATA_DIR / "cookies.json"

PLAN_DIR = Path(os.getenv("PLAN_DIR", os.path.expanduser("~/Desktop/刷题计划")))
PROGRESS_FILE = PLAN_DIR / "01_Hot100_进度表.md"
CHECKIN_FILE = PLAN_DIR / "02_每日打卡.md"
DASHBOARD_FILE = PLAN_DIR / "03_进度看板.md"


def load_credentials() -> dict:
    """加载凭证，优先从 cookies.json 读取，回退到 .env。"""
    if COOKIES_FILE.exists():
        try:
            data = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
            if data.get("LEETCODE_SESSION"):
                return {
                    "username": data.get("username", ""),
                    "session": data["LEETCODE_SESSION"],
                    "csrf": data.get("csrftoken", ""),
                }
        except (json.JSONDecodeError, KeyError):
            pass

    return {
        "username": os.getenv("LEETCODE_USERNAME", ""),
        "session": os.getenv("LEETCODE_SESSION", ""),
        "csrf": os.getenv("CSRF_TOKEN", ""),
    }
