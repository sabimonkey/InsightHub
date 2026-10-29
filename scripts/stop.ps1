$ErrorActionPreference = "Continue"
& (Join-Path $PSScriptRoot "manage.ps1") stop @args
exit $LASTEXITCODE
