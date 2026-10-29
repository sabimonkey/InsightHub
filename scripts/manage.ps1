param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status", "doctor")]
    [string]$Action = "start",
    [switch]$NoBrowser,
    [switch]$IncludeBgeOnStop
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "runtime\RuntimeLib.ps1")
$Paths = Get-InsightPaths -Root $Root

function Get-ManifestHashtable {
    if (-not (Test-Path $Paths.Manifest)) {
        return @{ version = 1; project_root = $Paths.Root; services = @{} }
    }
    $json = Get-Content $Paths.Manifest -Raw | ConvertFrom-Json
    $services = @{}
    if ($json.services) {
        foreach ($prop in $json.services.PSObject.Properties) {
            $services[$prop.Name] = @{
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
    return @{ version = 1; project_root = $Paths.Root; services = $services }
}

function Save-ManifestHashtable {
    param($Manifest)
    $Manifest | ConvertTo-Json -Depth 8 | Set-Content -Path $Paths.Manifest -Encoding UTF8
}

function Register-ManagedProcess {
    param([string]$Name, [System.Diagnostics.Process]$Process, [string]$CommandIdentity, [int]$Port = 0)
    $meta = Get-ProcessCommandLine -ProcessId $Process.Id
    $creationTime = if ($meta -and $meta.CreationDate) {
        $meta.CreationDate
    } else {
        # Preserve an ownership timestamp when Windows denies command-line
        # inspection. Test-ManagedIdentity uses it only alongside an exact
        # project root and port-listener PID check for API/frontend services.
        $Process.StartTime.ToUniversalTime().ToString("o")
    }
    $Manifest = Get-ManifestHashtable
    $Manifest.services[$Name] = @{
        service = $Name
        pid = $Process.Id
        started_at = (Get-Date).ToUniversalTime().ToString("o")
        command_identity = $CommandIdentity
        project_root = $Paths.Root
        port = if ($Port -gt 0) { $Port } else { $null }
        owned_by_launcher = $true
        creation_time = $creationTime
    }
    Save-ManifestHashtable $Manifest
}

function Start-InsightComponent {
    param(
        [string]$Name,
        [string]$File,
        [string[]]$ArgumentList,
        [string]$WorkDir,
        [string]$Identity,
        [int]$Port = 0,
        [scriptblock]$HealthyTest
    )
    $Manifest = Get-ManifestHashtable
    $record = $Manifest.services[$Name]
    if ($record -and (Test-ManagedIdentity -Record $record -ProjectRoot $Paths.Root)) {
        Write-RuntimeLog "$Name REUSE managed pid $($record.pid)" $Paths
        return
    }
    if ($Port -gt 0) {
        $pidOnPort = Get-ListeningPid -Port $Port
        if ($pidOnPort -and (& $HealthyTest)) {
            Write-RuntimeLog "$Name REUSE external pid $pidOnPort on port $Port" $Paths
            return
        }
        if ($pidOnPort) {
            throw "PORT_CONFLICT: $Name port $Port held by pid $pidOnPort"
        }
    }
    if ($Name -eq "worker" -and (Test-WorkerDetected -Python $Paths.Python -Backend $Paths.Backend)) {
        Write-RuntimeLog "worker REUSE (RQ registry)" $Paths
        return
    }
    New-Item -ItemType Directory -Force -Path $Paths.RunDir | Out-Null
    $proc = Start-Process -FilePath $File -ArgumentList $ArgumentList -WorkingDirectory $WorkDir -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Paths.RunDir "$Name.log") `
        -RedirectStandardError (Join-Path $Paths.RunDir "$Name.err.log") -PassThru
    Register-ManagedProcess -Name $Name -Process $proc -CommandIdentity $Identity -Port $Port
    if ($Port -gt 0) {
        $deadline = (Get-Date).AddSeconds(20)
        while ((Get-Date) -lt $deadline) {
            $listener = Get-ListeningPid -Port $Port
            if ($listener) {
                $listenerProc = Get-Process -Id $listener -ErrorAction SilentlyContinue
                if ($listenerProc) {
                    Register-ManagedProcess -Name $Name -Process $listenerProc -CommandIdentity $Identity -Port $Port
                }
                break
            }
            Start-Sleep -Milliseconds 500
        }
    }
    Write-RuntimeLog "$Name STARTED pid $($proc.Id)" $Paths
}

function Start-InsightHub {
    Write-RuntimeLog "=== InsightHub start ===" $Paths
    if ((Test-TcpPort -Port 5434) -and (Test-TcpPort -Port 6380)) {
        Write-RuntimeLog "PostgreSQL/Redis REUSE (ports already ready)" $Paths
    } else {
        if (-not (Ensure-DockerEngine -Paths $Paths)) { throw "DOCKER_ENGINE_UNAVAILABLE" }
        Ensure-ComposeServices -Paths $Paths
    }

    if (-not (Test-BgeHealthy) -and (Test-Path -LiteralPath $Paths.BgePython -PathType Leaf) -and (Test-Path -LiteralPath $Paths.BgeScript -PathType Leaf)) {
        Write-RuntimeLog "Starting BGE-M3..." $Paths
        $bgeDir = Split-Path $Paths.BgeScript -Parent
        Start-InsightComponent -Name "bge" -File $Paths.BgePython `
            -ArgumentList @("-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8011") `
            -WorkDir $bgeDir -Identity "server:app" -Port 8011 -HealthyTest { Test-BgeHealthy }
        $bgeDeadline = (Get-Date).AddMinutes(3)
        while ((Get-Date) -lt $bgeDeadline) {
            if (Test-BgeHealthy) { Write-RuntimeLog "BGE READY" $Paths; break }
            Start-Sleep -Seconds 3
        }
        if (-not (Test-BgeHealthy)) { Write-RuntimeLog "BGE DEGRADED (semantic retrieval may be limited)" $Paths }
    } elseif (Test-BgeHealthy) {
        Write-RuntimeLog "BGE REUSE" $Paths
    } else {
        Write-RuntimeLog "BGE SKIP (optional external service is not installed)" $Paths
    }

    Push-Location $Paths.Backend
    $redis = & $Paths.Python -c "from app.core.config import get_settings; print(get_settings().redis_url)"
    Pop-Location

    Start-InsightComponent -Name "api" -File $Paths.Python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8090") `
        -WorkDir $Paths.Backend -Identity "app.main:app" -Port 8090 -HealthyTest { Test-BackendHealthy -Python $Paths.Python }

    Start-InsightComponent -Name "worker" -File $Paths.Python `
        -ArgumentList @("-m", "rq.cli", "worker", "insighthub", "--url", $redis, "--worker-class", "rq.worker.SimpleWorker") `
        -WorkDir $Paths.Backend -Identity "rq.cli" -Port 0 -HealthyTest { Test-WorkerDetected -Python $Paths.Python -Backend $Paths.Backend }

    Start-InsightComponent -Name "frontend" -File "npm.cmd" `
        -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5174", "--strictPort") `
        -WorkDir $Paths.Frontend -Identity "vite" -Port 5174 -HealthyTest { Test-FrontendHealthy }

    if (-not (Wait-CoreReady -Paths $Paths -TimeoutSec 120)) {
        throw "CORE_SERVICES_NOT_READY: check logs under logs/runtime and data/run"
    }

    $status = Get-RuntimeStatusJson -Python $Paths.Python -Backend $Paths.Backend
    Show-StatusTable $status
    if ($status.overall -eq "FAILED") { throw "Overall runtime FAILED" }
    if ($status.overall -eq "STARTING") { throw "CORE_SERVICES_NOT_READY: overall STARTING" }

    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:5174"
    }
    Write-RuntimeLog "InsightHub start complete (overall=$($status.overall))" $Paths
}

function Show-Doctor {
    Push-Location $Paths.Backend
    & $Paths.Python -m app.runtime.cli doctor --json
    Pop-Location
}

switch ($Action) {
    "start" { Start-InsightHub }
    "stop" {
        Write-RuntimeLog "=== InsightHub stop (managed processes only) ===" $Paths
        Stop-ManagedServices -Paths $Paths -IncludeBge:$IncludeBgeOnStop
        Write-RuntimeLog "InsightHub stop complete (Docker/BGE external preserved by default)" $Paths
    }
    "restart" {
        & $PSCommandPath stop
        Start-Sleep -Seconds 2
        if ($NoBrowser) {
            & $PSCommandPath start -NoBrowser
        } else {
            & $PSCommandPath start
        }
    }
    "status" {
        $status = Get-RuntimeStatusJson -Python $Paths.Python -Backend $Paths.Backend
        Show-StatusTable $status
    }
    "doctor" { Show-Doctor }
}

exit 0
