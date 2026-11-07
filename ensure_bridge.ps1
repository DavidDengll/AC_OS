# ensure_bridge.ps1
# 确保宿主机桥接服务 host_agent_bridge.py 在后台静默运行（幂等，可重复调用）
#
# 熵灵容器通过 http://host.docker.internal:5555 访问宿主机桥接。
# 若桥接没起来，熵灵一睁眼就会因为连不上宿主机桥接而焦虑（皮质醇飙升）。
# 因此 start_ac_os.bat 必须在 docker compose up 之前调用本脚本。
#
# 返回码: 0 = 就绪/复用成功; 1 = 启动失败; 2 = 端口被其他程序占用
#
# 注意: 必须保存为 UTF-8 with BOM，否则 PowerShell 5.1 解析中文会报
#      Missing closing '}' —— 这是实测踩过的坑。
param(
    [int]$Port = 5555,
    [int]$WaitSeconds = 20,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

function Write-Line([string]$msg) {
    if (-not $Quiet) { Write-Host $msg }
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BridgePy = Join-Path $Root 'host_agent_bridge.py'
$LogDir = Join-Path $Root 'logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

if (-not (Test-Path $BridgePy)) {
    Write-Line ('  [ERROR] 找不到 host_agent_bridge.py: ' + $BridgePy)
    exit 1
}

function Get-PortOwnerPid([int]$p) {
    try {
        $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction Stop | Select-Object -First 1
        if ($c) { return [int]$c.OwningProcess }
    } catch { }
    return $null
}

function Test-IsOurBridge([int]$procId) {
    try {
        $proc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $procId) -ErrorAction Stop
        if (-not $proc) { return $false }
        return ($proc.CommandLine -like '*host_agent_bridge*')
    } catch { return $false }
}

# ---- 1) 已在运行则直接复用（幂等）----
$ownerId = Get-PortOwnerPid $Port
if ($ownerId -and (Test-IsOurBridge $ownerId)) {
    Write-Line ('  [OK] 宿主机桥接已在运行 (PID ' + $ownerId + ', 端口 ' + $Port + ' 就绪)')
    exit 0
}

# ---- 2) 端口被其他程序占用: 警告但不阻塞，不死锁 ----
if ($ownerId) {
    $pname = '?'
    try { $pname = (Get-Process -Id $ownerId -ErrorAction Stop).ProcessName } catch { }
    Write-Line ('  [WARN] 端口 ' + $Port + ' 已被其他程序占用: ' + $pname + ' (PID ' + $ownerId + ')')
    Write-Line '         桥接无法启动，熵灵将无法连接宿主机。'
    Write-Line '         请先释放该端口后再重试。本次继续启动容器，不做阻塞。'
    exit 2
}

# ---- 3) 静默拉起 ----
# 实测 1: Start-Process -RedirectStandardOutput/Error 会让调用方一直挂住
#        （重定向句柄被子进程继承），所以这里不加重定向。
# 实测 2: 桥接自身冷启动约 5.4 秒（Flask + docker_ok 探测），故默认等待 20 秒。
Write-Line '  [..] 宿主机桥接未运行，正在后台静默启动 ...'
try {
    $python = (Get-Command python -ErrorAction Stop).Source
} catch {
    Write-Line '  [ERROR] 找不到 python 命令，无法启动桥接。'
    exit 1
}

try {
    Start-Process -FilePath $python -ArgumentList @($BridgePy) -WorkingDirectory $Root -WindowStyle Hidden -PassThru | Out-Null
} catch {
    Write-Line ('  [WARN] 后台拉起异常: ' + $_.Exception.Message)
}

# ---- 4) 等待端口就绪 ----
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$ready = $null
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 400
    $ready = Get-PortOwnerPid $Port
    if ($ready) { break }
}

if ($ready) {
    Write-Line ('  [OK] 宿主机桥接已就绪 (PID ' + $ready + ', 端口 ' + $Port + ')')
    exit 0
}

# ---- 5) 失败诊断（不阻塞、不死锁）----
Write-Line ('  [WARN] 桥接未在 ' + $WaitSeconds + ' 秒内监听端口 ' + $Port)
Write-Line '         熵灵本次可能无法连接宿主机桥接，但容器仍会启动。'
exit 1
