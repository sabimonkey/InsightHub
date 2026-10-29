$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "manage.ps1") start @args
exit $LASTEXITCODE
