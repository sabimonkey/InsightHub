$ErrorActionPreference = "Stop"

function Get-InsightPaths {
    param([string]$Root)
    $localPython = Join-Path $Root ".venv\Scripts\python.exe"
    $pythonCandidates = @()
    if ($env:INSIGHTHUB_PYTHON) {
        if (-not (Test-Path -LiteralPath $env:INSIGHTHUB_PYTHON -PathType Leaf)) {
            throw "INSIGHTHUB_PYTHON does not point to an executable file"
        }
        $pythonCandidates += $env:INSIGHTHUB_PYTHON
    } else {
        $pythonCandidates += $localPython
        $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($pythonCommand) { $pythonCandidates += $pythonCommand.Source }
    }
    $pythonPath = $null
    foreach ($candidate in $pythonCandidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        & $candidate -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" *> $null
        if ($LASTEXITCODE -eq 0) { $pythonPath = $candidate; break }
        if ($env:INSIGHTHUB_PYTHON) { throw "INSIGHTHUB_PYTHON must point to Python 3.11" }
    }
    if (-not $pythonPath) {
        throw "Python 3.11 was not found. Create .venv or set INSIGHTHUB_PYTHON."
    }

    $bgePython = if ($env:BGE_M3_PYTHON) { $env:BGE_M3_PYTHON } else { $null }
    $bgeScript = if ($env:BGE_M3_SERVER_SCRIPT) { $env:BGE_M3_SERVER_SCRIPT } else { $null }
    @{
        Root = $Root
        Python = $pythonPath
        BgePython = $bgePython
        BgeScript = $bgeScript
        Backend = Join-Path $Root "backend"
        Frontend = Join-Path $Root "frontend"
        RunDir = Join-Path $Root "data\run"
        LogDir = Join-Path $Root "logs\runtime"
        Manifest = Join-Path $Root "data\run\managed_processes.json"
    }
}

function Write-RuntimeLog {
    param([string]$Message, [hashtable]$Paths)
    $Paths.LogDir | ForEach-Object { New-Item -ItemType Directory -Force -Path $_ | Out-Null }
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message
    Write-Host $line
    $file = Join-Path $Paths.LogDir ("{0:yyyy-MM-dd}.log" -f (Get-Date))
    Add-Content -Path $file -Value $line
}

function Test-TcpPort {
    param([string]$HostName = "127.0.0.1", [int]$Port, [int]$TimeoutMs = 1500)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        $ok = $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false) -and $client.Connected
        $client.Close()
        return $ok
    } catch {
        return $false
    }
}

function Get-ListeningPid {
    param([int]$Port)
    $line = netstat -ano | Select-String ":$Port\s" | Select-String "LISTENING" | Select-Object -First 1
    if (-not $line) { return $null }
    $procId = ($line.ToString().Trim() -split '\s+')[-1]
    if ($procId -match '^\d+$') { return [int]$procId }
    return $null
}

function Get-ProcessCommandLine {
    param([int]$ProcessId)
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $cim) { return $null }
    return @{
        CommandLine = $cim.CommandLine
        CreationDate = if ($cim.CreationDate) { $cim.CreationDate.ToUniversalTime().ToString("o") } else { $null }
    }
}

function Load-Manifest {
    param([string]$Path, [string]$ProjectRoot)
    if (-not (Test-Path $Path)) {
        return @{ version = 1; project_root = $ProjectRoot; services = @{} }
    }
    $raw = Get-Content $Path -Raw | ConvertFrom-Json
    if (-not $raw.services) { $raw | Add-Member -NotePropertyName services -NotePropertyValue @{} }
    return $raw
}

function Save-Manifest {
    param($Manifest, [string]$Path)
    $dir = Split-Path $Path -Parent
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $Manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $Path -Encoding UTF8
}

function Test-ManagedIdentity {
    param($Record, [string]$ProjectRoot)
    if (-not $Record) { return $false }
    $processId = if ($Record -is [hashtable]) { $Record["pid"] } else { $Record.pid }
    $commandIdentity = if ($Record -is [hashtable]) { $Record["command_identity"] } else { $Record.command_identity }
    $creationTime = if ($Record -is [hashtable]) { $Record["creation_time"] } else { $Record.creation_time }
    $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if (-not $proc) { return $false }
    $meta = Get-ProcessCommandLine -ProcessId $processId
    if (-not $meta -or -not $meta.CommandLine) {
        # Some Windows security contexts deny Win32_Process.CommandLine even for
        # a process launched by this user. A port-bound service may still be
        # verified safely using the launch manifest's project, creation time,
        # executable kind, and the exact listener PID. Never apply this fallback
        # to background workers or records without an owned port.
        $recordProjectRoot = if ($Record -is [hashtable]) { $Record["project_root"] } else { $Record.project_root }
        $port = if ($Record -is [hashtable]) { $Record["port"] } else { $Record.port }
        $service = if ($Record -is [hashtable]) { $Record["service"] } else { $Record.service }
        $expectedIdentity = if ($service -eq "api") { "app.main:app" } elseif ($service -eq "frontend") { "vite" } else { $null }
        if (-not $creationTime -or -not $port -or -not $recordProjectRoot -or $service -notin @("api", "frontend")) { return $false }
        if ($commandIdentity -ne $expectedIdentity) { return $false }
        if ([System.IO.Path]::GetFullPath($recordProjectRoot).TrimEnd('\') -ine [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')) { return $false }
        if ($proc.ProcessName -notin @("python", "pythonw", "node")) { return $false }
        try {
            $recordStarted = ([datetime]$creationTime).ToUniversalTime()
            $processStarted = $proc.StartTime.ToUniversalTime()
        } catch {
            return $false
        }
        if ([math]::Abs(($recordStarted - $processStarted).TotalSeconds) -gt 2) { return $false }
        return (Get-ListeningPid -Port ([int]$port)) -eq [int]$processId
    }
    if ($meta.CommandLine -notlike "*$commandIdentity*") { return $false }
    if ($creationTime -and $meta.CreationDate) {
        try {
            $recordCreation = ([datetime]$creationTime).ToUniversalTime().ToString("o")
            $processCreation = ([datetime]$meta.CreationDate).ToUniversalTime().ToString("o")
        } catch {
            return $false
        }
        if ($recordCreation -ne $processCreation) { return $false }
    }
    return $true
}

function Invoke-InsightPython {
    param([string]$Python, [string]$Backend, [string]$Code)
    & $Python -c $Code
}

function Get-RuntimeStatusJson {
    param([string]$Python, [string]$Backend)
    Push-Location $Backend
    try {
        $out = & $Python -m app.runtime.cli status --json 2>&1 | Out-String
        return $out | ConvertFrom-Json
    } finally {
        Pop-Location
    }
}

function Test-WorkerDetected {
    param([string]$Python, [string]$Backend)
    Push-Location $Backend
    try {
        $result = & $Python -c "from app.services.maintenance.system import worker_detected; print('1' if worker_detected() else '0')"
        return $result -eq "1"
    } finally {
        Pop-Location
    }
}

function Test-BackendHealthy {
    param([string]$Python)
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8090/health" -TimeoutSec 3
        if ($health.status -ne "ok") { return $false }
        $providers = Invoke-RestMethod -Uri "http://127.0.0.1:8090/api/llm/providers" -TimeoutSec 5
        $types = @($providers | ForEach-Object { $_.provider_type })
        return ($types -contains "ZAI") -and -not ($types | Where-Object { $_ -in @("LOCAL_OPENAI_COMPATIBLE", "DEEPSEEK", "SILICONFLOW", "GENERIC_OPENAI_COMPATIBLE") })
    } catch {
        return $false
    }
}

function Test-FrontendHealthy {
    try {
        $page = Invoke-WebRequest -Uri "http://127.0.0.1:5174/" -UseBasicParsing -TimeoutSec 3
        if ($page.StatusCode -ne 200) { return $false }
        $providers = Invoke-RestMethod -Uri "http://127.0.0.1:5174/api/llm/providers" -TimeoutSec 5
        $types = @($providers | ForEach-Object { $_.provider_type })
        return ($types -contains "ZAI") -and -not ($types | Where-Object { $_ -in @("LOCAL_OPENAI_COMPATIBLE", "DEEPSEEK", "SILICONFLOW", "GENERIC_OPENAI_COMPATIBLE") })
    } catch {
        return $false
    }
}

function Test-BgeHealthy {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8011/health" -UseBasicParsing -TimeoutSec 5
        return $resp.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Ensure-DockerEngine {
    param([hashtable]$Paths)
    $info = docker info 2>$null
    if ($LASTEXITCODE -eq 0) { return $true }
    Write-RuntimeLog "Docker Engine not ready; attempting Docker Desktop start" $Paths
    $desktop = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $desktop) {
        Start-Process $desktop | Out-Null
        $deadline = (Get-Date).AddMinutes(3)
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 5
            docker info 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $true }
        }
    }
    Write-RuntimeLog "DOCKER_ENGINE_UNAVAILABLE: Docker Desktop needs user attention" $Paths
    return $false
}

function Ensure-ComposeServices {
    param([hashtable]$Paths)
    Push-Location $Paths.Root
    docker compose up -d postgres redis
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }
    $deadline = (Get-Date).AddMinutes(2)
    while ((Get-Date) -lt $deadline) {
        $pg = Test-TcpPort -Port 5434
        $rd = Test-TcpPort -Port 6380
        if ($pg -and $rd) {
            Pop-Location
            return
        }
        Start-Sleep -Seconds 2
    }
    Pop-Location
    throw "PostgreSQL/Redis did not become ready in time"
}

function Start-ManagedService {
    param(
        [string]$Name,
        [string]$File,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [string]$CommandIdentity,
        [hashtable]$Paths,
        $Manifest
    )
    $record = $Manifest.services.$Name
    if ($record -and (Test-ManagedIdentity -Record $record -ProjectRoot $Paths.Root)) {
        Write-RuntimeLog "$Name REUSE (managed pid $($record.pid))" $Paths
        return "REUSE"
    }

    $portMap = @{ api = 8090; frontend = 5174; worker = 0; bge = 8011 }
    $port = $portMap[$Name]
    if ($port -gt 0) {
        $listener = Get-ListeningPid -Port $port
        if ($listener) {
            $healthy = switch ($Name) {
                "api" { Test-BackendHealthy -Python $Paths.Python }
                "frontend" { Test-FrontendHealthy }
                "bge" { Test-BgeHealthy }
                default { $true }
            }
            if ($healthy) {
                Write-RuntimeLog "$Name REUSE (external listener pid $listener on $port)" $Paths
                return "REUSE"
            }
            throw "PORT_CONFLICT: port $port in use by pid $listener but service unhealthy"
        }
    }

    if ($Name -eq "worker" -and (Test-WorkerDetected -Python $Paths.Python -Backend $Paths.Backend)) {
        Write-RuntimeLog "worker REUSE (RQ registry)" $Paths
        return "REUSE"
    }

    New-Item -ItemType Directory -Force -Path $Paths.RunDir | Out-Null
    $stdout = Join-Path $Paths.RunDir "$Name.log"
    $stderr = Join-Path $Paths.RunDir "$Name.err.log"
    $process = Start-Process -FilePath $File -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    Start-Sleep -Milliseconds 500
    $meta = Get-ProcessCommandLine -ProcessId $process.Id
    $entry = @{
        service = $Name
        pid = $process.Id
        started_at = (Get-Date).ToUniversalTime().ToString("o")
        command_identity = $CommandIdentity
        project_root = $Paths.Root
        port = if ($port -gt 0) { $port } else { $null }
        owned_by_launcher = $true
        creation_time = $meta.CreationDate
    }
    if (-not $Manifest.services) { $Manifest.services = @{} }
    $Manifest.services | Add-Member -NotePropertyName $Name -NotePropertyValue ($entry | ConvertTo-Json | ConvertFrom-Json) -Force
    # PowerShell hashtable vs PSCustomObject mess - use hashtable for manifest
    Write-RuntimeLog "$Name STARTED pid $($process.Id)" $Paths
    return "STARTED"
}

function Wait-CoreReady {
    param([hashtable]$Paths, [int]$TimeoutSec = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $api = Test-BackendHealthy -Python $Paths.Python
        $fe = Test-FrontendHealthy
        $wk = Test-WorkerDetected -Python $Paths.Python -Backend $Paths.Backend
        if ($api -and $fe -and $wk) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Stop-ManagedServices {
    param([hashtable]$Paths, [switch]$IncludeBge)
    if (-not (Test-Path $Paths.Manifest)) { return }
    $manifest = Get-Content $Paths.Manifest -Raw | ConvertFrom-Json
    $names = @("frontend", "worker", "api")
    if ($IncludeBge) { $names += "bge" }
    $remaining = @{}
    if ($manifest.services) {
        foreach ($prop in $manifest.services.PSObject.Properties) {
            $remaining[$prop.Name] = @{
                service = $prop.Value.service
                pid = [int]$prop.Value.pid
                started_at = $prop.Value.started_at
                command_identity = $prop.Value.command_identity
                project_root = $prop.Value.project_root
                port = $prop.Value.port
                owned_by_launcher = [bool]$prop.Value.owned_by_launcher
                creation_time = $prop.Value.creation_time
            }
        }
    }
    foreach ($name in $names) {
        if (-not $remaining.ContainsKey($name)) { continue }
        $record = $remaining[$name]
        if (-not (Test-ManagedIdentity -Record $record -ProjectRoot $Paths.Root)) {
            Write-RuntimeLog "skip stop $name (ownership not verified)" $Paths
            $remaining.Remove($name)
            continue
        }
        $processId = $record["pid"]
        Stop-Process -Id $processId -ErrorAction SilentlyContinue
        $wait = (Get-Date).AddSeconds(8)
        while ((Get-Date) -lt $wait) {
            if (-not (Get-Process -Id $processId -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 300
        }
        if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            Write-RuntimeLog "$name FORCE_STOP pid $processId" $Paths
        } else {
            Write-RuntimeLog "$name STOPPED pid $processId" $Paths
        }
        $remaining.Remove($name)
    }
    $out = @{ version = 1; project_root = $Paths.Root; services = $remaining }
    $out | ConvertTo-Json -Depth 8 | Set-Content -Path $Paths.Manifest -Encoding UTF8
    foreach ($legacy in @("frontend", "worker", "api")) {
        $legacyPid = Join-Path $Paths.RunDir "$legacy.pid"
        if (Test-Path $legacyPid) { Remove-Item $legacyPid -ErrorAction SilentlyContinue }
    }
}

function Show-StatusTable {
    param($Status)
    Write-Host ""
    Write-Host "InsightHub Runtime Status"
    foreach ($name in @("postgresql", "redis", "backend", "rq_worker", "frontend", "bge_m3", "chromium")) {
        $svc = $Status.services.$name
        if ($svc) {
            Write-Host ("{0,-14} {1,-10} {2}" -f $name, $svc.state, $svc.detail)
        }
    }
    Write-Host ""
    Write-Host ("Overall: {0}" -f $Status.overall)
    Write-Host ("Web URL: {0}" -f $Status.web_url)
}
