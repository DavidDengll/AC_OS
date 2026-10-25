@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
title AC_OS 一键心跳

rem  start_ac_os.bat -- 一键心跳启动（Windows）
rem    1. 快速环境自检   2. 确保 Ollama 在线
rem    3. 无黑框拉起 main.py --auto   4. 提示日志位置
rem  参数: --foreground  前台运行（调试用）

set "ROOT=%~dp0"
set "NL=%ROOT%newlivingthings"
set "MODEL=qwen3.5:0.8b"
set "FOREGROUND=0"
if /i "%~1"=="--foreground" set "FOREGROUND=1"

echo.
echo  ============================================================
echo              AC_OS  一键心跳启动
echo  ============================================================
echo.

echo  [检查] 运行环境 ...
set "PY_CMD="
if exist "%ROOT%.venv\Scripts\python.exe" set "PY_CMD=%ROOT%.venv\Scripts\python.exe"
if not defined PY_CMD (
    py -3 -c "import sys" >nul 2>&1 && set "PY_CMD=py -3"
)
if not defined PY_CMD (
    python -c "import sys" >nul 2>&1 && set "PY_CMD=python"
)
if not defined PY_CMD goto no_python
echo         [OK] Python 就绪 ( !PY_CMD! )

if not exist "%NL%\main.py" goto no_main
echo         [OK] 主程序存在: newlivingthings\main.py

set "OLLAMA_BIN="
for /f "delims=" %%p in ('where ollama 2^>nul') do if not defined OLLAMA_BIN set "OLLAMA_BIN=%%p"
if not defined OLLAMA_BIN if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_BIN=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not defined OLLAMA_BIN goto no_ollama

call :probe_api
if errorlevel 1 (
    echo         [..] Ollama 服务未运行，正在拉起 ...
    start "ollama" /min "%OLLAMA_BIN%" serve
    for /l %%i in (1,1,20) do (
        timeout /t 1 >nul
        call :probe_api
        if not errorlevel 1 goto api_ready
    )
    echo         [警告] Ollama 服务未能启动，将降级为本地兜底回复
    goto after_api
)
:api_ready
echo         [OK] Ollama 服务在线 (127.0.0.1:11434)
:after_api

"%OLLAMA_BIN%" list 2>nul | findstr /I /C:"%MODEL%" >nul 2>&1
if errorlevel 1 (
    echo         [警告] 未找到基础模型 %MODEL%，建议先运行 setup_env.bat
) else (
    echo         [OK] 基础模型 %MODEL% 已就绪
)

if "%FOREGROUND%"=="1" goto run_foreground

echo.
echo  [启动] 无黑框后台挂机运行 ...
start "" /b wscript.exe //nologo "%ROOT%run_entropy.vbs"

timeout /t 3 >nul
set "RUNNING=0"
for /f "delims=" %%i in ('tasklist /FI "IMAGENAME eq python.exe" /NH 2^>nul') do (
    echo %%i | findstr /I "python.exe" >nul && set "RUNNING=1"
)
if "%RUNNING%"=="1" (
    echo         [OK] 熵灵已在后台运行
) else (
    echo         [提示] 后台进程暂未检出，可能仍在加载模型，请稍候
)

echo.
echo  ------------------------------------------------------------
echo   日志目录 : %ROOT%logs\
echo   停止方式 : 双击 stop_entropy.bat
echo   前台调试 : start_ac_os.bat --foreground
echo  ------------------------------------------------------------
echo.
echo  窗口 5 秒后自动关闭，熵灵在后台继续运行。
timeout /t 5 >nul
goto the_end

:run_foreground
echo.
echo  [启动] 前台模式（Ctrl+C 停止）
echo  ------------------------------------------------------------
cd /d "%NL%"
%PY_CMD% main.py --auto
goto the_end

:no_python
echo         [错误] 未检测到 Python
echo                请先双击 setup_env.bat 完成环境初始化
pause
goto the_end

:no_main
echo         [错误] 找不到 newlivingthings\main.py
echo                请确认脚本放在 AC_OS 仓库根目录
pause
goto the_end

:no_ollama
echo         [警告] 未检测到 Ollama，程序仍可运行（仅本地兜底回复）

:the_end
endlocal
exit /b 0

:probe_api
if not defined PY_CMD exit /b 1
%PY_CMD% -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=3)" >nul 2>&1
exit /b %errorlevel%
