#!/bin/bash
# iiSU-CN-Scraper — macOS 一键启动脚本
# 用法: ./run_mac.sh

set -e
cd "$(dirname "$0")"

# ---- Python 解释器 ----
# 优先用项目自带的 .venv，否则回退到系统 python3
if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
else
    PY="$(command -v python3 || command -v python)"
fi

if [ -z "$PY" ]; then
    echo "❌ 未找到 Python，请先安装 Python 3.10+: https://www.python.org/downloads/macos/"
    exit 1
fi

echo "使用 Python: $PY"
"$PY" --version

# ---- 依赖检测 ----
if ! "$PY" -c "import flet" 2>/dev/null; then
    echo "⚠️  缺少依赖，正在安装..."
    if [ -x ".venv/bin/pip" ]; then
        .venv/bin/pip install -r requirements.txt
    else
        "$PY" -m pip install -r requirements.txt
    fi
fi

# ---- 启动 ----
echo "🚀 启动 iiSU CN Scraper..."
exec "$PY" main.py
