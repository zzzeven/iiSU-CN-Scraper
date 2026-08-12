@echo off
chcp 65001 >nul
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"

REM ============================================================
REM  iiSU-CN-Scraper — Windows 一键启动脚本
REM  自动: 选 Python → 建 venv → 装依赖 → 装 Playwright → 启动
REM ============================================================

echo ============================================================
echo   iiSU CN Scraper — Windows 启动
echo ============================================================

REM ---- 1) 选择 Python: 项目 venv -> py 启动器 -> python ----
set "PY="
if exist ".venv\Scripts\python.exe" (
    set "PY=%CD%\.venv\Scripts\python.exe"
) else (
    where py >nul 2>nul && set "PY=py -3"
    if not defined PY (
        where python >nul 2>nul && set "PY=python"
    )
)
if not defined PY (
    echo [错误] 未找到 Python 3.10+，请从 https://www.python.org/downloads/windows/ 安装
    echo        安装时务必勾选 "Add python.exe to PATH"
    pause
    exit /b 1
)
echo 使用 Python: %PY%
%PY% --version

REM ---- 版本检查 (需要 3.10+) ----
%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>nul
if errorlevel 1 (
    echo [错误] 需要 Python 3.10 及以上版本
    pause
    exit /b 1
)

REM ---- 2) 无 venv 则创建 ----
if not exist ".venv\Scripts\python.exe" (
    echo [提示] 创建虚拟环境 .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建 venv 失败
        pause
        exit /b 1
    )
    set "PY=%CD%\.venv\Scripts\python.exe"
)

REM ---- 3) 依赖缺失则安装 ----
%PY% -c "import flet" >nul 2>nul
if errorlevel 1 (
    echo [提示] 安装依赖: flet/requests/openai/playwright ...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
)

REM ---- 4) 检查/安装 Playwright Chromium (幂等, 已装则秒过) ----
echo [提示] 检查 Playwright Chromium ...
%PY% -m playwright install chromium
if errorlevel 1 (
    echo [警告] Chromium 安装失败 — GameGear 数据源将不可用, 其余功能正常
)

REM ---- 5) 启动 ----
echo.
echo 启动 iiSU CN Scraper ...
echo (关闭此窗口即退出程序)
%PY% main.py
pause
