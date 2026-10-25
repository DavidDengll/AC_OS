@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
title AC_OS Stop
echo.
echo  ============================================================
echo              AC_OS  Stop Entropy (background)
echo  ============================================================
echo.

set "ROOT=%~dp0"
set "PIDFILE=%ROOT%logs\entropy.pid"
set "COUNT=0"

rem --- 方式一：PID 文件（最快最准） ---
if not exist "%PIDFILE%" goto try_wmi
set "PID="
set /p PID=<"%PIDFILE%"
if "!PID!"=="" goto try_wmi
echo   [STOP] taskkill /F /PID !PID!
taskkill /F /PID !PID! >nul 2>&1
if not errorlevel 1 set /a COUNT+=1

:try_wmi
rem --- 方式二：WMI 兜底扫描所有含 main.py 的 python 进程 ---
for /f %%p in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue ^| Where-Object { $_.Name -eq $([char]39)python.exe$([char]39) -and $_.CommandLine -like $([char]39)*main.py*$([char]39) } ^| Select-Object -ExpandProperty ProcessId" 2^>nul') do (
    echo   [STOP] taskkill /F /PID %%p ^(scan^)
    taskkill /F /PID %%p >nul 2>&1
    set /a COUNT+=1
)

if exist "%PIDFILE%" del /q "%PIDFILE%" >nul 2>&1

if !COUNT! GTR 0 (
    echo.
    echo   [DONE] Stopped !COUNT! Entropy process^(es^).
) else (
    echo   [INFO] No running Entropy process found.
    echo          If it is still running, end python.exe in Task Manager.
)
echo.
pause
endlocal
exit /b 0
