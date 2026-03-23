"""后台守护：注册/卸载系统级定时任务，关终端也不影响。

支持的调度格式：
    10m / 30m       — 每 N 分钟
    1h / 2h         — 每 N 小时
    23:00           — 每天固定时间

macOS  → LaunchAgent (~/Library/LaunchAgents/)
Linux  → systemd user timer (~/.config/systemd/user/)
Windows → schtasks
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .config import DATA_DIR

SERVICE_ID = "com.offerpilot.sync"
REMIND_SERVICE_ID = "com.offerpilot.remind"
LOG_FILE = DATA_DIR / "sync.log"
REMIND_LOG_FILE = DATA_DIR / "remind.log"
SCHEDULE_FILE = DATA_DIR / "daemon_schedule.json"

REMIND_HOURS = [(10, 0), (17, 0), (22, 0)]


def _find_leetcode_bin() -> str:
    which = shutil.which("leetcode")
    if which:
        return str(Path(which).resolve())
    return f"{sys.executable} -m leetcode_auto.sync"


# ---------------------------------------------------------------------------
# 调度解析
# ---------------------------------------------------------------------------

class Schedule:
    """统一的调度配置。"""
    def __init__(self, mode: str, interval_seconds: int = 0,
                 hour: int = 0, minute: int = 0, raw: str = ""):
        self.mode = mode            # "interval" | "daily"
        self.interval_seconds = interval_seconds
        self.hour = hour
        self.minute = minute
        self.raw = raw

    def human_str(self) -> str:
        if self.mode == "interval":
            if self.interval_seconds >= 3600:
                return f"每 {self.interval_seconds // 3600} 小时"
            return f"每 {self.interval_seconds // 60} 分钟"
        return f"每天 {self.hour:02d}:{self.minute:02d}"

    def to_dict(self) -> dict:
        return {"mode": self.mode, "interval_seconds": self.interval_seconds,
                "hour": self.hour, "minute": self.minute, "raw": self.raw}

    @classmethod
    def from_dict(cls, d: dict) -> "Schedule":
        return cls(**d)


def parse_schedule(text: str) -> Schedule:
    """解析用户输入的调度字符串。

    支持格式：
        10m / 30m     — 每 N 分钟（最小 1 分钟）
        1h / 2h       — 每 N 小时
        23:00         — 每天固定时间
    """
    text = text.strip().lower()

    m = re.fullmatch(r"(\d+)m(?:in)?", text)
    if m:
        minutes = int(m.group(1))
        if minutes < 1:
            raise ValueError("最小间隔为 1 分钟")
        return Schedule("interval", interval_seconds=minutes * 60, raw=text)

    m = re.fullmatch(r"(\d+)h(?:r|our)?s?", text)
    if m:
        hours = int(m.group(1))
        if hours < 1:
            raise ValueError("最小间隔为 1 小时")
        return Schedule("interval", interval_seconds=hours * 3600, raw=text)

    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            raise ValueError("时间范围：00:00 ~ 23:59")
        return Schedule("daily", hour=h, minute=mi, raw=text)

    raise ValueError(
        f"无法识别的格式：{text}\n"
        "支持格式：10m / 30m / 1h / 2h / 23:00"
    )


def _save_schedule(sched: Schedule):
    SCHEDULE_FILE.write_text(
        json.dumps(sched.to_dict(), ensure_ascii=False), encoding="utf-8")


def _load_schedule() -> Optional[Schedule]:
    if SCHEDULE_FILE.exists():
        try:
            return Schedule.from_dict(
                json.loads(SCHEDULE_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# macOS: LaunchAgent
# ---------------------------------------------------------------------------

_PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
_PLIST_FILE = _PLIST_DIR / f"{SERVICE_ID}.plist"


def _plist_program_args(extra_args: list = None) -> str:
    lc_bin = _find_leetcode_bin()
    parts = lc_bin.split() if " " in lc_bin else [lc_bin]
    if extra_args:
        parts.extend(extra_args)
    return "\n".join(f"        <string>{p}</string>" for p in parts)


def _plist_content(sched: Schedule) -> str:
    prog = _plist_program_args()
    path_env = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")

    if sched.mode == "interval":
        trigger = (
            f"    <key>StartInterval</key>\n"
            f"    <integer>{sched.interval_seconds}</integer>"
        )
    else:
        trigger = (
            f"    <key>StartCalendarInterval</key>\n"
            f"    <dict>\n"
            f"        <key>Hour</key>\n"
            f"        <integer>{sched.hour}</integer>\n"
            f"        <key>Minute</key>\n"
            f"        <integer>{sched.minute}</integer>\n"
            f"    </dict>"
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{SERVICE_ID}</string>

    <key>ProgramArguments</key>
    <array>
{prog}
    </array>

{trigger}

    <key>StandardOutPath</key>
    <string>{LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>{LOG_FILE}</string>

    <key>RunAtLoad</key>
    <false/>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{path_env}</string>
        <key>OFFERPILOT_DAEMON</key>
        <string>1</string>
    </dict>
</dict>
</plist>"""


def _install_macos(sched: Schedule):
    _PLIST_DIR.mkdir(parents=True, exist_ok=True)
    _unload_macos(quiet=True)
    _PLIST_FILE.write_text(_plist_content(sched), encoding="utf-8")
    subprocess.run(["launchctl", "load", str(_PLIST_FILE)], check=True)
    print(f"已注册 macOS LaunchAgent，{sched.human_str()}自动同步。")
    print(f"日志文件：{LOG_FILE}")
    print(f"配置文件：{_PLIST_FILE}")


def _unload_macos(quiet: bool = False):
    if _PLIST_FILE.exists():
        subprocess.run(["launchctl", "unload", str(_PLIST_FILE)],
                       capture_output=True)
        _PLIST_FILE.unlink()
        if not quiet:
            print("已卸载 macOS LaunchAgent，后台同步已停止。")
    elif not quiet:
        print("未找到已注册的定时任务。")


def _status_macos():
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if SERVICE_ID in line:
            parts = line.split()
            pid = parts[0] if parts[0] != "-" else "待触发"
            sched = _load_schedule()
            print(f"状态：已注册")
            if sched:
                print(f"频率：{sched.human_str()}")
            print(f"进程：{pid}")
            print(f"配置：{_PLIST_FILE}")
            print(f"日志：{LOG_FILE}")
            _print_last_log()
            return
    print("状态：未注册")
    _print_help_hint()


# ---------------------------------------------------------------------------
# Linux: systemd user timer
# ---------------------------------------------------------------------------

_SYSTEMD_DIR = Path.home() / ".config" / "systemd" / "user"
_SERVICE_FILE = _SYSTEMD_DIR / "offerpilot-sync.service"
_TIMER_FILE = _SYSTEMD_DIR / "offerpilot-sync.timer"


def _systemd_on_calendar(sched: Schedule) -> str:
    if sched.mode == "interval":
        mins = sched.interval_seconds // 60
        if mins >= 60:
            hours = mins // 60
            return f"*-*-* 0/{hours}:00:00"
        return f"*-*-* *:0/{mins}:00"
    return f"*-*-* {sched.hour:02d}:{sched.minute:02d}:00"


def _install_linux(sched: Schedule):
    lc_bin = _find_leetcode_bin()
    _SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)

    _SERVICE_FILE.write_text(
        f"[Unit]\n"
        f"Description=OfferPilot sync\n"
        f"\n"
        f"[Service]\n"
        f"Type=oneshot\n"
        f"ExecStart={lc_bin}\n"
        f"StandardOutput=append:{LOG_FILE}\n"
        f"StandardError=append:{LOG_FILE}\n"
        f"Environment=PATH={os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}\n"
        f"Environment=OFFERPILOT_DAEMON=1\n",
        encoding="utf-8",
    )
    _TIMER_FILE.write_text(
        f"[Unit]\n"
        f"Description=OfferPilot sync timer\n"
        f"\n"
        f"[Timer]\n"
        f"OnCalendar={_systemd_on_calendar(sched)}\n"
        f"Persistent=true\n"
        f"\n"
        f"[Install]\n"
        f"WantedBy=timers.target\n",
        encoding="utf-8",
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now",
                    "offerpilot-sync.timer"], check=True)
    print(f"已注册 systemd 定时器，{sched.human_str()}自动同步。")
    print(f"日志文件：{LOG_FILE}")
    print(f"查看状态：systemctl --user status offerpilot-sync.timer")


def _unload_linux(quiet: bool = False):
    subprocess.run(["systemctl", "--user", "disable", "--now",
                    "offerpilot-sync.timer"], capture_output=True)
    for f in (_SERVICE_FILE, _TIMER_FILE):
        if f.exists():
            f.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    if not quiet:
        print("已卸载 systemd 定时器，后台同步已停止。")


def _status_linux():
    result = subprocess.run(
        ["systemctl", "--user", "is-active", "offerpilot-sync.timer"],
        capture_output=True, text=True,
    )
    active = result.stdout.strip() == "active"
    if active:
        sched = _load_schedule()
        print("状态：运行中")
        if sched:
            print(f"频率：{sched.human_str()}")
        info = subprocess.run(
            ["systemctl", "--user", "status", "offerpilot-sync.timer"],
            capture_output=True, text=True,
        )
        for line in info.stdout.splitlines():
            if "Trigger:" in line or "trigger:" in line.lower():
                print(f"下次触发：{line.strip()}")
    else:
        print("状态：未注册")
        _print_help_hint()
    print(f"日志：{LOG_FILE}")
    _print_last_log()


# ---------------------------------------------------------------------------
# Windows: schtasks
# ---------------------------------------------------------------------------

_TASK_NAME = "OfferPilot-Sync"


def _install_windows(sched: Schedule):
    lc_bin = _find_leetcode_bin()
    wrapped = f'cmd /c "set OFFERPILOT_DAEMON=1 && {lc_bin}"'

    if sched.mode == "interval":
        mins = sched.interval_seconds // 60
        cmd = [
            "schtasks", "/create", "/tn", _TASK_NAME,
            "/tr", wrapped, "/sc", "minute", "/mo", str(mins), "/f",
        ]
    else:
        time_str = f"{sched.hour:02d}:{sched.minute:02d}"
        cmd = [
            "schtasks", "/create", "/tn", _TASK_NAME,
            "/tr", wrapped, "/sc", "daily", "/st", time_str, "/f",
        ]

    subprocess.run(cmd, check=True)
    print(f"已注册 Windows 计划任务，{sched.human_str()}自动同步。")
    print(f"日志文件：{LOG_FILE}")
    print(f"查看状态：schtasks /query /tn {_TASK_NAME}")


def _unload_windows(quiet: bool = False):
    subprocess.run(["schtasks", "/delete", "/tn", _TASK_NAME, "/f"],
                   capture_output=True)
    if not quiet:
        print("已卸载 Windows 计划任务，后台同步已停止。")


def _status_windows():
    result = subprocess.run(
        ["schtasks", "/query", "/tn", _TASK_NAME],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        sched = _load_schedule()
        print("状态：已注册")
        if sched:
            print(f"频率：{sched.human_str()}")
        for line in result.stdout.splitlines():
            if line.strip():
                print(f"  {line.strip()}")
    else:
        print("状态：未注册")
        _print_help_hint()
    print(f"日志：{LOG_FILE}")
    _print_last_log()


# ---------------------------------------------------------------------------
# 共用
# ---------------------------------------------------------------------------


def _print_help_hint():
    print()
    print("用法：leetcode --daemon <频率>")
    print("  leetcode --daemon 30m     每 30 分钟")
    print("  leetcode --daemon 1h      每小时")
    print("  leetcode --daemon 23:00   每天 23:00")


def _print_last_log():
    if not LOG_FILE.exists():
        return
    lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    recent = lines[-8:] if len(lines) > 8 else lines
    if recent:
        print(f"\n最近日志（{LOG_FILE.name}）：")
        for line in recent:
            print(f"  {line}")


def install_daemon(schedule_str: str):
    """解析调度格式并注册系统级定时任务。"""
    try:
        sched = parse_schedule(schedule_str)
    except ValueError as e:
        print(f"错误：{e}")
        sys.exit(1)

    system = platform.system()
    if system == "Darwin":
        _install_macos(sched)
    elif system == "Linux":
        _install_linux(sched)
    elif system == "Windows":
        _install_windows(sched)
    else:
        print(f"不支持的系统：{system}，请使用 --cron 前台模式。")
        sys.exit(1)

    _save_schedule(sched)

    print(f"\n关闭终端后仍会在后台自动运行。")
    print("卸载：leetcode --daemon stop")
    print("查看：leetcode --daemon status")


def uninstall_daemon():
    """卸载系统级定时任务。"""
    system = platform.system()
    if system == "Darwin":
        _unload_macos()
    elif system == "Linux":
        _unload_linux()
    elif system == "Windows":
        _unload_windows()
    else:
        print(f"不支持的系统：{system}")

    if SCHEDULE_FILE.exists():
        SCHEDULE_FILE.unlink()


def daemon_status():
    """查看后台定时任务状态。"""
    system = platform.system()
    print(f"系统：{system}\n")
    if system == "Darwin":
        _status_macos()
    elif system == "Linux":
        _status_linux()
    elif system == "Windows":
        _status_windows()
    else:
        print(f"不支持的系统：{system}")


# ---------------------------------------------------------------------------
# 每日提醒守护
# ---------------------------------------------------------------------------

_REMIND_PLIST_FILE = _PLIST_DIR / f"{REMIND_SERVICE_ID}.plist"
_REMIND_SERVICE_FILE = _SYSTEMD_DIR / "offerpilot-remind.service"
_REMIND_TIMER_FILE = _SYSTEMD_DIR / "offerpilot-remind.timer"
_REMIND_TASK_PREFIX = "OfferPilot-Remind"


def _remind_times_str() -> str:
    return "、".join(f"{h:02d}:{m:02d}" for h, m in REMIND_HOURS)


# --- macOS ---

def _remind_plist_content() -> str:
    prog = _plist_program_args(["--remind"])
    path_env = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    entries = "\n".join(
        f"        <dict>\n"
        f"            <key>Hour</key>\n"
        f"            <integer>{h}</integer>\n"
        f"            <key>Minute</key>\n"
        f"            <integer>{m}</integer>\n"
        f"        </dict>"
        for h, m in REMIND_HOURS
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{REMIND_SERVICE_ID}</string>

    <key>ProgramArguments</key>
    <array>
{prog}
    </array>

    <key>StartCalendarInterval</key>
    <array>
{entries}
    </array>

    <key>StandardOutPath</key>
    <string>{REMIND_LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>{REMIND_LOG_FILE}</string>

    <key>RunAtLoad</key>
    <false/>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{path_env}</string>
    </dict>
</dict>
</plist>"""


def _install_remind_macos():
    _PLIST_DIR.mkdir(parents=True, exist_ok=True)
    _unload_remind_macos(quiet=True)
    _REMIND_PLIST_FILE.write_text(_remind_plist_content(), encoding="utf-8")
    subprocess.run(["launchctl", "load", str(_REMIND_PLIST_FILE)], check=True)
    print(f"已注册每日提醒，每天 {_remind_times_str()} 推送通知。")
    print(f"日志文件：{REMIND_LOG_FILE}")


def _unload_remind_macos(quiet: bool = False):
    if _REMIND_PLIST_FILE.exists():
        subprocess.run(["launchctl", "unload", str(_REMIND_PLIST_FILE)],
                       capture_output=True)
        _REMIND_PLIST_FILE.unlink()
        if not quiet:
            print("已卸载每日提醒。")
    elif not quiet:
        print("未找到已注册的提醒任务。")


def _status_remind_macos():
    result = subprocess.run(["launchctl", "list"],
                            capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if REMIND_SERVICE_ID in line:
            print(f"状态：已注册")
            print(f"提醒时间：每天 {_remind_times_str()}")
            print(f"日志：{REMIND_LOG_FILE}")
            return
    print("状态：未注册")
    print("启用：leetcode --remind-daemon")


# --- Linux ---

def _install_remind_linux():
    lc_bin = _find_leetcode_bin()
    _SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
    _REMIND_SERVICE_FILE.write_text(
        f"[Unit]\nDescription=OfferPilot reminder\n\n"
        f"[Service]\nType=oneshot\n"
        f"ExecStart={lc_bin} --remind\n"
        f"StandardOutput=append:{REMIND_LOG_FILE}\n"
        f"StandardError=append:{REMIND_LOG_FILE}\n"
        f"Environment=PATH={os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}\n",
        encoding="utf-8",
    )
    on_calendars = "\n".join(
        f"OnCalendar=*-*-* {h:02d}:{m:02d}:00" for h, m in REMIND_HOURS)
    _REMIND_TIMER_FILE.write_text(
        f"[Unit]\nDescription=OfferPilot reminder timer\n\n"
        f"[Timer]\n{on_calendars}\nPersistent=true\n\n"
        f"[Install]\nWantedBy=timers.target\n",
        encoding="utf-8",
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now",
                    "offerpilot-remind.timer"], check=True)
    print(f"已注册每日提醒，每天 {_remind_times_str()} 推送通知。")


def _unload_remind_linux(quiet: bool = False):
    subprocess.run(["systemctl", "--user", "disable", "--now",
                    "offerpilot-remind.timer"], capture_output=True)
    for f in (_REMIND_SERVICE_FILE, _REMIND_TIMER_FILE):
        if f.exists():
            f.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    if not quiet:
        print("已卸载每日提醒。")


def _status_remind_linux():
    result = subprocess.run(
        ["systemctl", "--user", "is-active", "offerpilot-remind.timer"],
        capture_output=True, text=True)
    if result.stdout.strip() == "active":
        print(f"状态：已注册")
        print(f"提醒时间：每天 {_remind_times_str()}")
    else:
        print("状态：未注册")
        print("启用：leetcode --remind-daemon")
    print(f"日志：{REMIND_LOG_FILE}")


# --- Windows ---

def _install_remind_windows():
    lc_bin = _find_leetcode_bin()
    for h, m in REMIND_HOURS:
        task_name = f"{_REMIND_TASK_PREFIX}-{h:02d}{m:02d}"
        subprocess.run([
            "schtasks", "/create", "/tn", task_name,
            "/tr", f'cmd /c "{lc_bin} --remind"',
            "/sc", "daily", "/st", f"{h:02d}:{m:02d}", "/f",
        ], check=True)
    print(f"已注册每日提醒，每天 {_remind_times_str()} 推送通知。")


def _unload_remind_windows(quiet: bool = False):
    for h, m in REMIND_HOURS:
        task_name = f"{_REMIND_TASK_PREFIX}-{h:02d}{m:02d}"
        subprocess.run(["schtasks", "/delete", "/tn", task_name, "/f"],
                       capture_output=True)
    if not quiet:
        print("已卸载每日提醒。")


def _status_remind_windows():
    found = False
    for h, m in REMIND_HOURS:
        task_name = f"{_REMIND_TASK_PREFIX}-{h:02d}{m:02d}"
        result = subprocess.run(["schtasks", "/query", "/tn", task_name],
                                capture_output=True)
        if result.returncode == 0:
            found = True
    if found:
        print(f"状态：已注册")
        print(f"提醒时间：每天 {_remind_times_str()}")
    else:
        print("状态：未注册")
        print("启用：leetcode --remind-daemon")
    print(f"日志：{REMIND_LOG_FILE}")


# --- 跨平台入口 ---

def install_remind_daemon():
    """注册每日提醒定时任务（10:00/17:00/22:00）。"""
    system = platform.system()
    if system == "Darwin":
        _install_remind_macos()
    elif system == "Linux":
        _install_remind_linux()
    elif system == "Windows":
        _install_remind_windows()
    else:
        print(f"不支持的系统：{system}")
        sys.exit(1)
    print("\n关闭终端后仍会按时推送提醒。")
    print("卸载：leetcode --remind-daemon stop")
    print("查看：leetcode --remind-daemon status")


def uninstall_remind_daemon():
    """卸载每日提醒定时任务。"""
    system = platform.system()
    if system == "Darwin":
        _unload_remind_macos()
    elif system == "Linux":
        _unload_remind_linux()
    elif system == "Windows":
        _unload_remind_windows()


def remind_daemon_status():
    """查看每日提醒任务状态。"""
    system = platform.system()
    print(f"系统：{system}\n")
    if system == "Darwin":
        _status_remind_macos()
    elif system == "Linux":
        _status_remind_linux()
    elif system == "Windows":
        _status_remind_windows()
    else:
        print(f"不支持的系统：{system}")
