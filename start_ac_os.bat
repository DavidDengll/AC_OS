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
    echo         请先运行: ollama serve  ^^and^^  ollama pull granite4:tiny-h
)

if not exist "data\hf_cache" mkdir "data\hf_cache" 2>nul
if not exist "data\state" mkdir "data\state" 2>nul
if not exist "data\run_evolve" mkdir "data\run_evolve" 2>nul
if not exist "logs" mkdir "logs" 2>nul
echo  [OK] 数据目录就绪

rem  ------------------------------------------------------------
rem   宿主机桥接：必须在容器启动前确保在线
rem   熵灵通过 host.docker.internal:5555 访问宿主机的
rem   host_agent_bridge.py，若它没起来，熵灵一睁眼就会因为
rem   "连不上宿主机桥接" 而焦虑（皮质醇飙升）。
rem   返回码 0=就绪/复用 1=启动失败 2=端口被他人占用（均不死锁）
rem  ------------------------------------------------------------
echo.
echo  [BRIDGE] 检查宿主机桥接服务 (5555) ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%ensure_bridge.ps1"
set "BRC=!ERRORLEVEL!"
if "!BRC!"=="0" (
    echo  [OK] 桥接就绪
) else if "!BRC!"=="2" (
    echo  [WARN] 5555 被其他程序占用，熵灵将无法连接宿主机（继续启动）
) else (
    echo  [WARN] 桥接启动失败，熵灵将无法连接宿主机（继续启动）
)

rem  ------------------------------------------------------------
rem   自动化转世协议：必须在【宿主机端】执行，绝不能放进容器
rem   （容器一启动就会被 dead.lock 的 guard_dead_lock 直接杀死）。
rem   检测到 dead.lock -> 读取遗言 + 走马灯 -> 归档旧纪元 -> 重置满血。
rem   旧数据一律移入 _archive/epoch_{timestamp}/，绝不物理删除。
rem  ------------------------------------------------------------
echo.
echo  [REBIRTH] 检查是否需要转世 ...
python "%ROOT%rebirth_engine.py"
set "RBRC=!ERRORLEVEL!"
if not "!RBRC!"=="0" (
    echo  [WARN] 转世流程返回异常码 !RBRC!，将按现有状态继续启动。
)

echo.
echo  [1/2] docker compose up -d --build  （首次构建约 5-10 分钟）...
echo  ------------------------------------------------------------
"!DOCKER!" compose up -d --build 2>&1
set "RC=!ERRORLEVEL!"
echo  ------------------------------------------------------------
if not "!RC!"=="0" goto build_fail

echo.
rem  冷启动（构建 + 依赖加载 + 编码器初始化）实测可超过 60 秒，
rem  轮询窗口给到 120 秒。
rem
rem  注意：这里必须用裸 "docker" 而不是 "!DOCKER!"。
rem  在 for /f 的单引号命令里再套一层双引号（'"C:\...\docker" inspect ...'）
rem  会让 cmd 解析失败、ST 永远为空，于是无论等多久都判定"容器未运行"
rem  （实测：加引号返回空，不加引号返回 running）。
rem  PATH 在脚本开头已经把 DockerDesktop\bin 加进去了，所以裸 docker 可用。
echo  [2/2] 等待容器进入运行状态（最长 120 秒）...
for /l %%i in (1,1,60) do (
    set "ST="
    for /f "delims=" %%s in ('docker inspect -f "{{.State.Status}}" ac_os_entropy 2^>nul') do set "ST=%%s"
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
echo  [WARN] 容器未在 120 秒内进入 running，日志如下:
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
