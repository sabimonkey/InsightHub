$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# This verifier must be safe to run beside a live user installation. It does
# not connect to the configured database, scan user storage, or start/stop any
# application services. Runtime installation is validated in a separately
# named Compose project as part of release qualification.

$lockPath = Join-Path $Root "backend/requirements-release.lock"
if (-not (Test-Path -LiteralPath $lockPath)) {
    throw "Missing backend/requirements-release.lock"
}
$lockLines = Get-Content -LiteralPath $lockPath | Where-Object { $_ -and -not $_.StartsWith("#") }
if ($lockLines.Count -lt 1 -or ($lockLines | Where-Object { $_ -notmatch '^[A-Za-z0-9_.-]+==[^=]+$' })) {
    throw "Runtime dependency lock must contain exact package pins only"
}

$previous = @{}
foreach ($name in @("POSTGRES_PASSWORD", "COMPOSE_PROJECT_NAME", "WEB_PORT", "POSTGRES_HOST_PORT", "REDIS_HOST_PORT")) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}
try {
    $env:POSTGRES_PASSWORD = [guid]::NewGuid().ToString("N")
    $env:COMPOSE_PROJECT_NAME = "insighthub_release_config_check"
    $env:WEB_PORT = "18080"
    $env:POSTGRES_HOST_PORT = "15434"
    $env:REDIS_HOST_PORT = "16380"
    docker compose -f compose.release.yaml config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose configuration is invalid" }
} finally {
    foreach ($name in $previous.Keys) {
        if ($null -eq $previous[$name]) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], "Process")
        }
    }
}

Write-Host "RELEASE CONFIG VERIFY OK (read-only; no configured user database or storage accessed)"
exit 0
