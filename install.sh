#!/bin/bash
set -e

echo "=== LeetCode Hot100 每日同步工具 - 安装 ==="
echo

# 检查 Python3
if ! command -v python3 &>/dev/null; then
    echo "错误：未找到 python3，请先安装 Python 3.9+"
    echo
    if [[ "$OSTYPE" == darwin* ]]; then
        echo "  macOS:   brew install python3"
    elif [[ -f /etc/debian_version ]]; then
        echo "  Ubuntu:  sudo apt install python3 python3-pip"
    elif [[ -f /etc/redhat-release ]]; then
        echo "  CentOS:  sudo yum install python3 python3-pip"
    fi
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "检测到 Python $PY_VERSION"

# 安装项目
echo
echo "正在安装..."
cd "$(dirname "$0")"
python3 -m pip install -e . --quiet

# 检查 leetcode 命令是否在 PATH 中
LEETCODE_BIN=$(python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))")/leetcode

if command -v leetcode &>/dev/null; then
    echo
    echo "安装完成！现在可以直接使用："
    echo
    echo "  leetcode              同步今日刷题记录"
    echo "  leetcode --status     查看刷题进度"
    echo "  leetcode --login      重新登录"
    echo "  leetcode --cron 23:00 每天定时自动同步"
    echo
elif [[ -f "$LEETCODE_BIN" ]]; then
    SCRIPTS_DIR=$(dirname "$LEETCODE_BIN")
    echo
    echo "安装完成！检测到 leetcode 命令不在 PATH 中。"
    echo "请先执行以下命令将其加入 PATH（只需一次）："
    echo
    SHELL_RC="$HOME/.zshrc"
    [[ "$SHELL" == */bash ]] && SHELL_RC="$HOME/.bashrc"
    echo "  echo 'export PATH=\"$SCRIPTS_DIR:\$PATH\"' >> $SHELL_RC"
    echo "  source $SHELL_RC"
    echo
    echo "然后就可以使用 leetcode 命令了。"
    echo
else
    echo
    echo "安装完成！请使用以下方式运行："
    echo
    echo "  python3 -m leetcode_auto.sync"
    echo
fi
