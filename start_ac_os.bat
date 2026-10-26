@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
title AC_OS - Docker Start
echo.
echo  ============================================================
echo        AC_OS  /  Entropy   -   Docker 一键启动
echo  ============================================================
echo.
rem  双击本文件：构建镜像并在后台启动容器
set "ROOT=%~dp0"
cd /d "%ROOT%"

set "DOCKER="
for /f "delims=" %%p in ('where docker 2^>nul') do if not defined DOCKER set "DOCKER=%%p"
if not defined DOCKER if exist "%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe" (
    set "DOCKER=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe"
    set "PATH=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin;%PATH%"
)
if not defined DOCKER goto no_docker
echo  [OK] docker: !DOCKER!

"!DOCKER!" info >nul 2>&1
if errorlevel 1 goto no_engine
for /f "delims=" %%v in ('"!DOCKER!" info --format "{{.ServerVersion}}" 2^>nul') do set "SRV=%%v"
echo  [OK] Docker 引擎已就绪 (server !SRV!)

set "OLLAMA_OK=0"
for /f %%i in ('powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri http://127.0.0.1:11434/api/tags -TimeoutSec 3 -UseBasicParsing).StatusCode } catch { 0 }"') do if "%%i"=="200" set "OLLAMA_OK=1"
if "!OLLAMA_OK!"=="1" (
    echo  [OK] 宿主机 Ollama 在线 ^(127.0.0.1:11434^)
) else (
    echo  [WARN] 宿主机 Ollama 未响应，容器将只能本地兜底回复
    echo         请先运行: ollama serve  ^^and^^  ollama pull qwen3.5:0.8b
)

if not exist "data\hf_cache" mkdir "data\hf_cache" 2>nul
if not exist "data\state" mkdir "data\state" 2>nul
if not exist "data\run_evolve" mkdir "data\run_evolve" 2>nul
if not exist "logs" mkdir "logs" 2>nul
echo  [OK] 数据目录就绪

echo.
echo  [1/2] docker compose up -d --build  （首次构建约 5-10 分钟）...
echo  ------------------------------------------------------------
"!DOCKER!" compose up -d --build 2>&1
set "RC=!ERRORLEVEL!"
echo  ------------------------------------------------------------
if not "!RC!"=="0" goto build_fail

echo.
echo  [2/2] 等待容器进入运行状态 ...
for /l %%i in (1,1,30) do (
    set "ST="
    for /f "delims=" %%s in ('"!DOCKER!" inspect -f "{{.State.Status}}" ac_os_entropy 2^>nul') do set "ST=%%s"
    if "!ST!"=="running" goto up_ok
    ping -n 2 127.0.0.1 >nul
)
goto up_timeout

:up_ok
echo  [OK] 容器已运行
echo.
echo  ============================================================
echo    [DONE] 熵灵容器已在后台运行
echo.
echo    看实时日志 : docker logs -f ac_os_entropy
echo    进容器看看 : docker exec -it ac_os_entropy bash
echo    停止容器   : 双击 stop_ac_os.bat
echo    源码目录   : .\newlivingthings ^(已挂载^)
echo  ============================================================

echo  最近 15 行日志:
"!DOCKER!" logs --tail 15 ac_os_entropy 2>&1
goto done

:up_timeout
echo  [WARN] 容器未在 60 秒内进入 running，日志如下:
"!DOCKER!" logs --tail 30 ac_os_entropy 2>&1
goto done

:build_fail
echo.
echo  [ERROR] 构建或启动失败，退出码 !RC!。
echo          常见原因：网络慢导致 pip 超时，可重试一次。
goto pause_done

:no_docker
echo  [ERROR] 未找到 docker 命令，请确认 Docker Desktop 已安装。
goto pause_done

:no_engine
echo  [ERROR] Docker 引擎未就绪，请等 Docker Desktop 显示 Engine running。

:pause_done
pause

:done
echo.
pause
endlocal
exit /b 0
