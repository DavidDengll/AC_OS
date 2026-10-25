@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
title AC_OS Environment Setup

rem ============================================================
rem  AC_OS one-click setup (Windows)
rem    setup_env.bat              full install
rem    setup_env.bat --check-only check only, download nothing
rem    setup_env.bat --skip-model skip "ollama pull"
rem    setup_env.bat --skip-deps  skip pip install
rem    setup_env.bat -h           help
rem ============================================================

set "CHECK_ONLY=0"
set "SKIP_MODEL=0"
set "SKIP_DEPS=0"
set "MODEL=qwen3.5:0.8b"
set "ROOT=%~dp0"
set "DEPS_DIR=%ROOT%newlivingthings\.pydeps"
set "REQ_FILE=%ROOT%newlivingthings\requirements.txt"

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--check-only" set "CHECK_ONLY=1"
if /i "%~1"=="--check"      set "CHECK_ONLY=1"
if /i "%~1"=="--skip-model" set "SKIP_MODEL=1"
if /i "%~1"=="--skip-deps"  set "SKIP_DEPS=1"
if /i "%~1"=="-h"           goto show_help
if /i "%~1"=="--help"       goto show_help
shift
goto parse_args

:show_help
echo.
echo   AC_OS setup
echo     setup_env.bat              full install
echo     setup_env.bat --check-only check only
echo     setup_env.bat --skip-model skip model pull
echo     setup_env.bat --skip-deps  skip pip install
goto :eof

:args_done
cls
echo.
echo  ============================================================
echo              AC_OS  Environment Setup   (Windows)
echo  ============================================================
if "%CHECK_ONLY%"=="1" echo    Mode: CHECK ONLY (nothing will be downloaded)
echo.

set "FAIL=0"
set "PY_CMD="

rem ---------------- [1/3] Python ----------------
echo  [1/3] Checking Python ...
if exist "%ROOT%.venv\Scripts\python.exe" set "PY_CMD=%ROOT%.venv\Scripts\python.exe"
if not defined PY_CMD (
    py -3 -c "import sys" >nul 2>&1 && set "PY_CMD=py -3"
)
if not defined PY_CMD (
    python -c "import sys" >nul 2>&1 && set "PY_CMD=python"
)
if defined PY_CMD (
    for /f "delims=" %%v in ('%PY_CMD% --version 2^>^&1') do set "PY_VER=%%v"
    echo         [OK] found !PY_VER! ^( !PY_CMD! ^)
    %PY_CMD% -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo         [ERROR] Python too old, need 3.9+.
        set "FAIL=1"
    )
) else (
    echo         [ERROR] Python not found.
    echo                 Install from https://www.python.org/downloads/
    echo                 Remember to tick "Add Python to PATH".
    set "FAIL=1"
)

rem ---------------- [2/3] Ollama ----------------
echo.
echo  [2/3] Checking Ollama ...
set "OLLAMA_BIN="
for /f "delims=" %%p in ('where ollama 2^>nul') do if not defined OLLAMA_BIN set "OLLAMA_BIN=%%p"
if not defined OLLAMA_BIN if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_BIN=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"

if defined OLLAMA_BIN goto has_ollama
echo         [ERROR] Ollama not found.
echo                 Install it first: https://ollama.com/download
set "FAIL=1"
goto after_ollama

:has_ollama
for /f "delims=" %%v in ('"%OLLAMA_BIN%" --version 2^>^&1') do set "OLLAMA_VER=%%v"
echo         [OK] found Ollama ^( !OLLAMA_VER! ^)
echo              path: !OLLAMA_BIN!

call :probe_api
if errorlevel 1 call :start_ollama
call :probe_api
if errorlevel 1 (
    echo         [WARN] Ollama service not reachable, please run: ollama serve
) else (
    echo         [OK] Ollama service online ^(127.0.0.1:11434^)
)

call :model_present
if not errorlevel 1 goto model_ready
if "%SKIP_MODEL%"=="1" goto model_skipped
if "%CHECK_ONLY%"=="1" goto model_missing
echo         Base model %MODEL% not found, downloading ^(~1.3GB^) ...
echo         --------------------------------------------
"%OLLAMA_BIN%" pull %MODEL%
echo         --------------------------------------------
if errorlevel 1 (
    echo         [ERROR] Model download failed, check your network.
    set "FAIL=1"
    goto after_ollama
)
echo         [OK] Model ready.
goto after_ollama

:model_ready
echo         [OK] Base model %MODEL% already present, skip download.
goto after_ollama

:model_skipped
echo         [SKIP] Model pull skipped ^(--skip-model^).
goto after_ollama

:model_missing
echo         [MISSING] Model %MODEL% not found ^(full run will download it^).

:after_ollama

rem ---------------- [3/3] Python deps ----------------
echo.
echo  [3/3] Installing Python dependencies ...
if not exist "%REQ_FILE%" (
    echo         [ERROR] requirements not found: %REQ_FILE%
    set "FAIL=1"
    goto summary
)
if not defined PY_CMD goto summary
if "%SKIP_DEPS%"=="1" (
    echo         [SKIP] Dependency install skipped ^(--skip-deps^).
    goto summary
)
if "%CHECK_ONLY%"=="1" (
    call :check_deps
    goto summary
)

echo         Installing base dependencies ...
%PY_CMD% -m pip install -r "%REQ_FILE%" --disable-pip-version-check
if errorlevel 1 (
    echo         [WARN] Some packages failed, try a mirror:
    echo                %PY_CMD% -m pip install -r "%REQ_FILE%" -i https://pypi.tuna.tsinghua.edu.cn/simple
    set "FAIL=1"
    goto summary
)
echo         [OK] Base dependencies installed.

echo.
echo         Installing finetune deps into .pydeps ^(isolated^) ...
%PY_CMD% -m pip install --target "%DEPS_DIR%" --no-deps psutil peft accelerate --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo         [WARN] Finetune deps failed. Main program still works,
    echo                only the idle self-finetune feature is affected.
) else (
    echo         [OK] Finetune dependencies installed.
)

:summary
echo.
echo  ============================================================
if "%FAIL%"=="0" (
    echo    [DONE] Environment ready. You can start Entropy now:
    echo.
    echo        cd newlivingthings
    echo        python main.py
) else (
    echo    [ATTENTION] Problems found above. Fix them before running main.py.
)
echo  ============================================================
echo.
if "%CHECK_ONLY%"=="1" goto the_end
pause

:the_end
if "%FAIL%"=="0" (endlocal & exit /b 0) else (endlocal & exit /b 1)

rem ================= subroutines =================

:probe_api
if not defined PY_CMD exit /b 1
%PY_CMD% -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=3)" >nul 2>&1
exit /b %errorlevel%

:start_ollama
echo         Ollama service not running, starting "ollama serve" ...
start "ollama" /min "%OLLAMA_BIN%" serve
for /l %%i in (1,1,15) do (
    timeout /t 1 >nul
    call :probe_api
    if not errorlevel 1 exit /b 0
)
exit /b 1

:model_present
"%OLLAMA_BIN%" list 2>nul | findstr /I /C:"%MODEL%" >nul 2>&1
exit /b %errorlevel%

:check_deps
set "DEPS_MISSING="
for %%p in (openai jieba ddgs gymnasium numpy sentence_transformers) do (
    %PY_CMD% -c "import %%p" >nul 2>&1
    if errorlevel 1 set "DEPS_MISSING=!DEPS_MISSING! %%p"
)
if defined DEPS_MISSING (
    echo         [MISSING] not installed:!DEPS_MISSING!
    echo                  full run will install them.
) else (
    echo         [OK] All base dependencies present.
)
exit /b 0
