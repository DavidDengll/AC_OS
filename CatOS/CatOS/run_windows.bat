@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
REM 让 wsl.exe 以 UTF-8 输出, 避免中文乱码
set WSL_UTF8=1

REM ======================================================================
REM  CatOS 一键构建 + 运行 (Windows -> WSL Ubuntu)
REM
REM  用法:
REM    run_windows.bat setup     首次使用: 安装编译/运行依赖 (需输入 sudo 密码)
REM    run_windows.bat           编译 + 建软盘镜像 + 启动 QEMU
REM    run_windows.bat nobuild   跳过编译, 直接启动 QEMU
REM    run_windows.bat clean     清理构建产物后退出
REM
REM  说明:
REM    - 构建在 WSL 的 Ubuntu 内完成 (build.sh 需要 nasm + mingw gcc)
REM    - QEMU 窗口由 WSLg 提供, 不需要额外安装 X Server
REM ======================================================================

set "DISTRO=Ubuntu"
set "PROJ=/mnt/d/DSH-Workspace/CatOS/CatOS"
set "PROJW=D:\DSH-Workspace\CatOS\CatOS"
set "MODE=%~1"

REM ---------- 1. 检查 wsl.exe ----------
where wsl.exe >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 找不到 wsl.exe, 请先安装 WSL:  wsl --install
    goto :fail
)

REM ---------- 2. 检查 Ubuntu 发行版 ----------
wsl.exe -d %DISTRO% -- true >nul 2>&1
if errorlevel 1 (
    echo [ERROR] WSL 发行版 "%DISTRO%" 不可用。
    echo         首次安装:  wsl --install -d Ubuntu
    echo         若提示需要重启, 请重启后再运行本脚本。
    goto :fail
)

REM ---------- 3. 依赖安装模式 ----------
if /I "%MODE%"=="setup" (
    echo [*] 在 Ubuntu 中安装编译与运行依赖 ...
    echo     ^(会提示输入你的 Linux 密码^)
    echo.
    wsl.exe -d %DISTRO% -- bash -lc "sudo apt update && sudo apt install -y build-essential nasm qemu-system-x86 gcc-multilib gcc-mingw-w64-i686 && chmod +x /mnt/d/DSH-Workspace/CatOS/CatOS/build.sh"
    if errorlevel 1 (
        echo.
        echo [ERROR] 依赖安装失败, 请检查网络或 apt 源。
        goto :fail
    )
    echo.
    echo [*] 依赖安装完成, 现在可以直接运行 run_windows.bat
    goto :done
)

REM ---------- 4. 清理模式 ----------
if /I "%MODE%"=="clean" (
    echo [*] 清理构建产物 ...
    wsl.exe -d %DISTRO% --cd %PROJ% -- ./build.sh clean
    goto :done
)

REM ---------- 5. 编译并生成可引导镜像 ----------
if /I not "%MODE%"=="nobuild" (
    echo [*] 在 WSL 中编译 CatOS 并生成 catos.img ...
    echo.
    wsl.exe -d %DISTRO% --cd %PROJ% -- ./build.sh image
    if errorlevel 1 (
        echo.
        echo [ERROR] 构建失败。常见原因:
        echo         1^) 缺少工具链, 先执行:  run_windows.bat setup
        echo         2^) build.sh 没有执行权限:
        echo            chmod +x /mnt/d/DSH-Workspace/CatOS/CatOS/build.sh
        goto :fail
    )
)

REM ---------- 6. 组装 QEMU 参数 ----------
if not exist "%PROJW%\catos.img" (
    echo [ERROR] 找不到 %PROJW%\catos.img, 请先完整构建一次。
    goto :fail
)

set "QARGS=-drive file=catos.img,if=floppy,format=raw"
set "HASHD=0"
if exist "%PROJW%\catos_hd32.img" (
    set "QARGS=%QARGS% -drive file=catos_hd32.img,format=raw"
    set "HASHD=1"
)

REM ---------- 7. 启动 QEMU ----------
echo.
echo [*] 启动 QEMU ...
echo     qemu-system-i386 %QARGS%
echo.
if "%HASHD%"=="1" (
    echo [*] 引导盘: catos.img ^(FAT12 软盘^)   硬盘: catos_hd32.img ^(FAT32^)
) else (
    echo [*] 引导盘: catos.img ^(FAT12 软盘^)   未找到 catos_hd32.img, 仅软盘启动
)
echo.
wsl.exe -d %DISTRO% --cd %PROJ% -- qemu-system-i386 %QARGS%

if errorlevel 1 (
    echo.
    echo [ERROR] QEMU 启动失败。请确认:
    echo         - 已安装:  sudo apt install -y qemu-system-x86
    echo         - WSLg 正常:  wsl --version
    goto :fail
)

echo.
echo [*] QEMU 已退出。
goto :done

:fail
echo.
pause
exit /b 1

:done
exit /b 0
