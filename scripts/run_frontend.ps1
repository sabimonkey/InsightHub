$ErrorActionPreference = "Stop"
$Frontend = Join-Path (Split-Path -Parent $PSScriptRoot) "frontend"
Set-Location $Frontend
npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
exit $LASTEXITCODE
