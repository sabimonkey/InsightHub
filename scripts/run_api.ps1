$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "runtime\RuntimeLib.ps1")
$Paths = Get-InsightPaths -Root $Root
$Python = $Paths.Python
$Backend = $Paths.Backend
Set-Location $Backend
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8090
exit $LASTEXITCODE
