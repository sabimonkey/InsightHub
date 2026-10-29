$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Error "Missing .env. Copy .env.example to .env and set POSTGRES_PASSWORD and DATABASE_URL."
}
docker compose up -d
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "PostgreSQL: 127.0.0.1:5434"
Write-Host "Redis: 127.0.0.1:6380"
Write-Host "Start API: .\scripts\run_api.ps1"
Write-Host "Start frontend: .\scripts\run_frontend.ps1"
exit 0
