@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
title AC_OS - Docker Stop
echo.
echo  ============================================================
echo        AC_OS  /  Entropy   -   Docker 停止
echo  ============================================================
echo.
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "DOCKER="
for /f "delims=" %%p in ('where docker 2^>nul') do if not defined DOCKER set "DOCKER=%%p"
if not defined DOCKER if exist "%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe" (
    set "DOCKER=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe"
    set "PATH=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin;%PATH%"
)
if not defined DOCKER goto no_docker

"!DOCKER!" info >nul 2>&1
if errorlevel 1 goto no_engine

echo  [..] 正在停止容器 ...
"!DOCKER!" compose down 2>&1
if errorlevel 1 (
    echo  [WARN] compose down 失败，尝试强制移除 ...
    "!DOCKER!" rm -f ac_os_entropy >nul 2>&1
)

"!DOCKER!" ps -a --filter "name=ac_os_entropy" --format "{{.Names}}" 2>nul | findstr /I "ac_os_entropy" >nul
if errorlevel 1 (
    echo.
    echo  [DONE] 容器已停止并移除。
) else (
    echo.
    echo  [WARN] 容器仍在运行，请手动执行: docker rm -f ac_os_entropy
)

rem  ------------------------------------------------------------
rem   顺带停掉宿主机桥接，避免它长期占着 5555 端口
rem   （桥接是 start_ac_os.bat 静默拉起的，停止时一并收走更干净）
rem  ------------------------------------------------------------
echo.
echo  [..] 正在停止宿主机桥接服务 ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*host_agent_bridge*' } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; Write-Host ('  [OK] 已停止桥接 PID ' + $_.ProcessId) } catch { } }; exit 0"
echo  [OK] 桥接处理完毕
goto done

:no_docker
echo  [ERROR] 未找到 docker 命令。
goto done

:no_engine
echo  [WARN] Docker 引擎未运行，容器不在运行。

:done
echo.
pause
endlocal
exit /b 0
