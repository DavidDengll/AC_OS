@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
title AC_OS Docker
echo.
echo  ============================================================
echo           AC_OS  Docker one-click launcher
echo  ============================================================
echo.

set "ROOT=%~dp0"
cd /d "%ROOT%"

rem ---------- 1. Docker 是否可用 ----------
where docker >nul 2>&1
if errorlevel 1 goto no_docker

docker info >nul 2>&1
if errorlevel 1 goto no_engine
echo  [OK] Docker 可用

rem ---------- 2. 选择 compose 命令 ----------
set "COMPOSE=docker compose"
docker compose version >nul 2>&1
if errorlevel 1 (
    where docker-compose >nul 2>&1
    if errorlevel 1 goto no_compose
    set "COMPOSE=docker-compose"
)
echo  [OK] 使用: !COMPOSE!

rem ---------- 3. 准备数据目录 ----------
if not exist "data\hf_cache" mkdir "data\hf_cache"
if not exist "data\state" mkdir "data\state"
if not exist "data\run_evolve" mkdir "data\run_evolve"
if not exist "logs" mkdir "logs"
echo  [OK] 数据目录已就绪

rem ---------- 4. 检查宿主机 Ollama 模型 ----------
set "OLLAMA_BIN="
for /f "delims=" %%p in ('where ollama 2^>nul') do if not defined OLLAMA_BIN set "OLLAMA_BIN=%%p"
if not defined OLLAMA_BIN if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_BIN=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if defined OLLAMA_BIN (
    "%OLLAMA_BIN%" list 2>nul | findstr /I /C:"qwen3.5:0.8b" >nul 2>&1
    if errorlevel 1 (
        echo  [WARN] 宿主机未找到 qwen3.5:0.8b，容器会连不上模型
        echo         请先在宿主机执行: ollama pull qwen3.5:0.8b
    ) else (
        echo  [OK] 宿主机已有 qwen3.5:0.8b
    )
) else (
    echo  [WARN] 宿主机未安装 Ollama，容器将无法调用大模型
)

rem ---------- 5. 构建并启动 ----------
echo.
echo  [1/2] 构建镜像（首次约需几分钟）...
!COMPOSE! build
if errorlevel 1 goto build_fail

echo.
echo  [2/2] 后台启动容器 ...
!COMPOSE! up -d
if errorlevel 1 goto up_fail

echo.
echo  ============================================================
echo    [DONE] AC_OS 容器已在后台运行
echo.
echo    查看日志 : docker logs -f ac_os_entropy
echo    进入容器 : docker exec -it ac_os_entropy bash
echo    停止容器 : docker compose down
echo    数据目录 : %ROOT%data\  ^(模型缓存/记忆/进化产物^)
echo  ============================================================
echo.
timeout /t 5 >nul 2>&1
goto the_end

:no_docker
echo  [ERROR] 未检测到 Docker。
echo          请安装 Docker Desktop: https://www.docker.com/products/docker-desktop
echo          安装后重开此窗口再运行。
goto fail

:no_engine
echo  [ERROR] Docker 已安装但引擎未启动。
echo          请双击启动 Docker Desktop，等图标变绿后重试。
goto fail

:no_compose
echo  [ERROR] 未找到 docker compose / docker-compose。
echo          请升级 Docker Desktop 到自带 compose 的版本。
goto fail

:build_fail
echo.
echo  [ERROR] 镜像构建失败，请看上方日志。
goto fail

:up_fail
echo.
echo  [ERROR] 容器启动失败，请尝试: docker compose logs

:fail
echo.
pause

:the_end
endlocal
exit /b 0
