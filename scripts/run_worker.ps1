$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "runtime\RuntimeLib.ps1")
$Paths = Get-InsightPaths -Root $Root
$Python = $Paths.Python
$Backend = $Paths.Backend
Set-Location $Backend
$RedisUrl = & $Python -c "from app.core.config import get_settings; print(get_settings().redis_url)"
& $Python -m rq.cli worker insighthub --url $RedisUrl --worker-class rq.worker.SimpleWorker
exit $LASTEXITCODE
