import json
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

DATA_DIR = Path(os.getenv("LEETCODE_AUTO_DIR", os.path.expanduser("~/.leetcode_auto")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(DATA_DIR / ".env")

# LeetCode 站点：cn (中国站) 或 us (国际站)
LEETCODE_SITE = os.getenv("LEETCODE_SITE", "cn").lower()
LEETCODE_API_URL = "https://leetcode.com/graphql/" if LEETCODE_SITE == "us" else "https://leetcode.cn/graphql/"
LEETCODE_BASE_URL = "https://leetcode.com" if LEETCODE_SITE == "us" else "https://leetcode.cn"
COOKIES_FILE = DATA_DIR / "cookies.json"

# 数据文件统一存放在 DATA_DIR/data 下，不再在桌面创建文件
_OLD_PLAN_DIR = Path(os.path.expanduser("~/Desktop/刷题计划"))
PLAN_DIR = Path(os.getenv("PLAN_DIR", str(DATA_DIR / "data")))
PROGRESS_FILE = PLAN_DIR / "01_Hot100_进度表.md"
CHECKIN_FILE = PLAN_DIR / "02_每日打卡.md"
DASHBOARD_FILE = PLAN_DIR / "03_进度看板.md"
OPTIMIZE_FILE = PLAN_DIR / "04_优化建议.md"


# AI 分析配置（支持 claude / openai）
AI_PROVIDER = os.getenv("AI_PROVIDER", "").lower()         # "claude" or "openai"
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "")                       # 留空则使用默认模型
AI_BASE_URL = os.getenv("AI_BASE_URL", "")                 # 自定义 API 地址（可选）

# 周报推送
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")                   # Slack/飞书/企微 webhook
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_TO = os.getenv("SMTP_TO", "")                           # 收件人邮箱


def get_ai_config() -> dict:
    """返回 AI 配置，含默认模型。"""
    provider = AI_PROVIDER
    model = AI_MODEL
    if not model:
        if provider == "claude":
            model = "claude-sonnet-4-20250514"
        elif provider == "openai":
            model = "gpt-4o"
    return {
        "provider": provider,
        "api_key": AI_API_KEY,
        "model": model,
        "base_url": AI_BASE_URL,
        "enabled": bool(provider and AI_API_KEY),
    }


# ---------------------------------------------------------------------------
# 刷题计划配置
# ---------------------------------------------------------------------------

PLAN_CONFIG_FILE = DATA_DIR / "plan_config.json"

_DEFAULT_PLAN_CONFIG = {
    "rounds": 5,
    "intervals": [1, 3, 7, 14],       # R2=+1d, R3=+3d, R4=+7d, R5=+14d
    "daily_new": 5,                     # 每日新题建议数
    "daily_review": 10,                 # 每日复习建议数
    "deadline": "",                     # 截止日期，格式 YYYY-MM-DD，空=不设置
    "problem_list": "hot100",           # 当前题单：hot100 / offer75 / top150
}


def load_plan_config() -> dict:
    """加载计划配置，缺失则返回默认值。"""
    config = dict(_DEFAULT_PLAN_CONFIG)
    if PLAN_CONFIG_FILE.exists():
        try:
            saved = json.loads(PLAN_CONFIG_FILE.read_text(encoding="utf-8"))
            config.update(saved)
        except (json.JSONDecodeError, IOError):
            pass
    # 确保 intervals 长度 = rounds - 1
    rounds = config["rounds"]
    intervals = config["intervals"]
    if len(intervals) < rounds - 1:
        defaults = [1, 3, 7, 14, 30, 60, 90]
        while len(intervals) < rounds - 1:
            intervals.append(defaults[len(intervals)] if len(intervals) < len(defaults) else intervals[-1] * 2)
    config["intervals"] = intervals[:rounds - 1]
    return config


def save_plan_config(config: dict):
    """保存计划配置。"""
    PLAN_CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def get_round_keys(config: dict = None) -> tuple:
    """根据配置生成轮次键名 ('r1', 'r2', ...)。"""
    if config is None:
        config = load_plan_config()
    return tuple(f"r{i}" for i in range(1, config["rounds"] + 1))


def get_review_intervals(config: dict = None) -> dict:
    """根据配置生成复习间隔字典 {'r2': 1, 'r3': 3, ...}。"""
    if config is None:
        config = load_plan_config()
    intervals = config["intervals"]
    return {f"r{i+2}": intervals[i] for i in range(len(intervals))}


def migrate_from_desktop():
    """如果旧桌面目录有数据而新目录没有，自动迁移。"""
    if not _OLD_PLAN_DIR.exists():
        return
    if PLAN_DIR.exists() and any(PLAN_DIR.iterdir()):
        return
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    migrated = []
    for f in _OLD_PLAN_DIR.iterdir():
        if f.is_file():
            shutil.copy2(f, PLAN_DIR / f.name)
            migrated.append(f.name)
    if migrated:
        print(f"已从桌面迁移刷题数据：{', '.join(migrated)}")
        print(f"新数据目录：{PLAN_DIR}")
        print(f"桌面旧文件可手动删除：{_OLD_PLAN_DIR}\n")


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
