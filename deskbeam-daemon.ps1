$ErrorActionPreference = 'Stop'

# Resolve python: prefer the project venv (created by start.bat with
# requirements.txt), then PATH python, then common install paths.
$exe = $null
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    $exe = $venvPy
} else {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        $exe = $cmd.Source
    } else {
        $candidates = @(
            "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
            "$env:ProgramFiles\Python312\python.exe",
            "$env:ProgramFiles\Python\Python\312\python.exe"
        )
        $exe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
}
if (-not $exe) {
    throw "Python not found. Install Python or create .venv first."
}

# Read the listen port from config.json (fallback 8770).
$port = 8770
try {
    $cfg = Get-Content (Join-Path $PSScriptRoot "config.json") -Raw | ConvertFrom-Json
    if ($cfg.port) { $port = [int]$cfg.port }
} catch {}

$projName = [System.IO.Path]::GetFileName($PSScriptRoot.TrimEnd('\'))
# Firewall rule tag: "DeskBeam-UDP" -> "DeskBeamUDP", "DeskBeam" -> "DeskBeam"
# (matches the names start.bat creates, so the two never duplicate rules).
$ruleTag = $projName -replace '-', ''

function Repair-Deps {
    # A .venv that exists but is missing packages makes server.py die at import
    # and wedges the restart loop. Check imports and install (with a mirror
    # fallback) exactly like start.bat does. Only meaningful for the venv.
    if (-not (Test-Path $venvPy)) { return }
    & $exe -c "import websockets, av, aiortc, numpy, cv2, dxcam" 2>$null
    if ($LASTEXITCODE -eq 0) { return }
    Log "[deskbeam] dependencies missing - installing..."
    & $exe -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        Log "[deskbeam] direct PyPI failed - retrying via Tsinghua mirror..."
        & $exe -m pip install -r (Join-Path $PSScriptRoot "requirements.txt") `
            -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60 --retries 5
    }
}

function Ensure-Firewall {
    # 两条规则,缺一不可:
    #   端口规则 —— 网页/信令(TCP $port)。局域网直连要用它;注意 Tailscale Serve
    #               是反代到 127.0.0.1、走回环,回环不过防火墙,所以那条路不需要它。
    #   程序规则 —— RTP/WebRTC 的入站 UDP 落在 ICE 协商出的**临时端口**上,固定端口
    #               规则覆盖不到,只能按程序放行(TCP+UDP)。
    # 原来只有程序规则,于是"只跑 daemon"的机器(AGENTS.md 说这样就行)在局域网上
    # 连不进 8770 —— 文档与实现矛盾,这里补上。
    # 远程地址按实际用法收紧: LocalSubnet(局域网/WSL) + Tailscale 的 v4/v6 段。
    # 本机可能有公网 IPv6,一条 远程地址=Any 的入站放行等于对公网开放。
    # 需要用别的来源(其它 VPN/公网直连)时,把它的网段加进 $allow。
    # 计划任务以 RunLevel=Highest 运行,所以这些调用有权限。
    $allow = @('LocalSubnet', '100.64.0.0/10', 'fd7a:115c:a1e0::/48')
    $spec = @(
        @{ n = "$ruleTag-$port";  kind = 'port'; desc = "TCP $port (web/signalling)" },
        @{ n = "$ruleTag-python"; kind = 'prog'; desc = "program allow (RTP ephemeral ports)" }
    )
    foreach ($r in $spec) {
        try {
            $existing = Get-NetFirewallRule -DisplayName $r.n -ErrorAction SilentlyContinue
            if ($existing) {
                # 已存在也要对齐远程地址(老机器上可能是 Any)
                Set-NetFirewallRule -DisplayName $r.n -RemoteAddress $allow -ErrorAction SilentlyContinue
                continue
            }
            if ($r.kind -eq 'port') {
                New-NetFirewallRule -DisplayName $r.n -Direction Inbound -Action Allow `
                    -Protocol TCP -LocalPort $port -RemoteAddress $allow -Profile Any | Out-Null
            } else {
                New-NetFirewallRule -DisplayName $r.n -Direction Inbound -Action Allow `
                    -Program $exe -RemoteAddress $allow -Profile Any | Out-Null
            }
            Log "[deskbeam] firewall: added inbound allow $($r.n) ($($r.desc))"
        } catch {
            Log "[deskbeam] firewall: could not add $($r.n) ($($_.Exception.Message))"
        }
    }
}

function Stop-PortOwners {
    # Same as start.bat: free the listen port before each start.  A leftover
    # instance would otherwise make the new server fail to bind (Errno 10048)
    # and wedge the daemon into an endless crash/restart loop.
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Get-NetUDPEndpoint -LocalPort $port -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 500
}

$exeArgs = @("$PSScriptRoot\server.py")
$pidFile = "$env:TEMP\deskbeam-pid-$projName.txt"
$logFile = Join-Path $PSScriptRoot "daemon.log"

Set-Location -LiteralPath $PSScriptRoot

function Log([string]$msg) {
    # 计划任务会丢弃 stdout,所以不落盘的话,每次重启的退出码和存活时长就全丢了
    # —— 而这正是区分"正常退出"和"原生崩溃"的唯一线索:Python 层异常会写进
    # server.log,而 C 层崩溃(PortAudio/WASAPI 之类)什么都不留。
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Write-Output $line
    try {
        if ((Test-Path -LiteralPath $logFile) -and
            (Get-Item -LiteralPath $logFile).Length -gt 262144) {
            # 与 server.log 同策略:超过 256KB 只保留后半。
            $all = @(Get-Content -LiteralPath $logFile)
            $keep = [int]($all.Count / 2)
            Set-Content -LiteralPath $logFile -Value $all[$keep..($all.Count - 1)] -Encoding utf8
        }
        Add-Content -LiteralPath $logFile -Value $line -Encoding utf8
    } catch {}
}

function Format-ExitCode([int]$code) {
    # 原生崩溃码是有符号负数(0xC0000005 -> -1073741819)。
    # **不要**写 [uint32]($code -band 0xFFFFFFFF):PowerShell 会对负数抛
    # "无法转换为 UInt32",而本脚本顶部是 $ErrorActionPreference='Stop',异常会
    # 直接干掉 daemon —— 结果是"进程崩了,但 daemon 既不记录也不重启",恰好是
    # 这个日志最该起作用的场景(踩过一次)。走 BitConverter 永不抛。
    $u = [BitConverter]::ToUInt32([BitConverter]::GetBytes([int]$code), 0)
    $hex = '0x{0:X8}' -f $u
    switch ($hex) {
        '0xC0000005' { return "$code ($hex 访问违例)" }
        '0xC0000409' { return "$code ($hex 快速失败/栈溢出)" }
        '0xC0000374' { return "$code ($hex 堆损坏)" }
        '0xC00000FD' { return "$code ($hex 栈溢出)" }
        default { return "$code ($hex)" }
    }
}

Repair-Deps
Ensure-Firewall

while ($true) {
    # 看门狗**绝不能被自己的代码搞死**:任何意外都只记录 + 退避后重试。
    # 曾经因为 Format-ExitCode 对负数崩溃码抛异常(叠加顶部的
    # $ErrorActionPreference='Stop'),daemon 在"被监控进程崩了"这个它唯一该起
    # 作用的场景下静默退出 —— 既不记录退出码,也不重启服务。
    try {
        if (Test-Path $pidFile) {
            $oldPid = Get-Content $pidFile -Raw
            if ($oldPid -match '^\d+$') {
                taskkill /PID $oldPid /F 2>$null
                Start-Sleep -Seconds 2
            }
        }
        Stop-PortOwners

        Log "[deskbeam] Starting DeskBeam..."
        $started = Get-Date
        $p = Start-Process -FilePath $exe -ArgumentList $exeArgs -WindowStyle Hidden -PassThru
        $p.Id | Set-Content $pidFile
        # 注意:Windows 上 .venv\Scripts\python.exe 是个 launcher,它会再起一个
        # 真正的解释器作为子进程,所以"这里记的 PID"和"实际监听端口的 PID"不是
        # 同一个 —— 属正常现象。launcher 会透传子进程的退出码,退出码仍然有效。
        Log "[deskbeam] DeskBeam started (PID $($p.Id), exe $exe)"

        $p.WaitForExit()
        $code = $p.ExitCode
        $lived = (Get-Date) - $started
        try { $desc = Format-ExitCode $code } catch { $desc = "$code" }
        Log "[deskbeam] DeskBeam exited (code $desc, lived $([int]$lived.TotalSeconds)s)"

        if ($code -eq 0) {
            Log "[deskbeam] Exited normally, restarting in 5s..."
            Start-Sleep -Seconds 5
        } elseif ($lived.TotalSeconds -lt 5) {
            # Immediate crash: likely a port/config problem. Back off so the
            # watchdog does not spin a tight loop and spam the log.
            Log "[deskbeam] Crashed immediately, restarting in 10s..."
            Start-Sleep -Seconds 10
        } else {
            Log "[deskbeam] Crashed, restarting in 2s..."
            Start-Sleep -Seconds 2
        }
    } catch {
        Log "[deskbeam] watchdog error: $($_.Exception.Message)"
        Start-Sleep -Seconds 5
    }
}
