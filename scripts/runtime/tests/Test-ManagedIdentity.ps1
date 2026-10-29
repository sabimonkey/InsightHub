$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\RuntimeLib.ps1")

$script:processCreation = "2026-10-28T01:00:00.0000000Z"
function Get-ProcessCommandLine {
    param([int]$ProcessId)
    return @{
        CommandLine = '"python.exe" -m uvicorn app.main:app --port 8090'
        CreationDate = $script:processCreation
    }
}

$serialized = @{ pid = $PID; command_identity = "app.main:app"; creation_time = $script:processCreation } |
    ConvertTo-Json |
    ConvertFrom-Json
$record = @{
    pid = [int]$serialized.pid
    command_identity = $serialized.command_identity
    creation_time = $serialized.creation_time
}

if (-not ($record.creation_time -is [datetime])) {
    throw "Expected ConvertFrom-Json to produce a DateTime creation_time value."
}
if (-not (Test-ManagedIdentity -Record $record -ProjectRoot (Get-Location).Path)) {
    throw "Matching PID, command, and ISO creation time should be accepted."
}

$record.creation_time = $record.creation_time.AddSeconds(1)
if (Test-ManagedIdentity -Record $record -ProjectRoot (Get-Location).Path) {
    throw "A different process creation time must be rejected."
}

$record.creation_time = $script:processCreation
$record.command_identity = "different-command"
if (Test-ManagedIdentity -Record $record -ProjectRoot (Get-Location).Path) {
    throw "A different command identity must be rejected."
}

# When Windows denies command-line inspection, only an exact project-owned
# port listener with the manifest creation time may use the safe fallback.
$script:fallbackProcess = [pscustomobject]@{
    ProcessName = "python"
    StartTime = [datetime]"2026-10-28T02:31:21Z"
}
function Get-Process { param([int]$Id, [string]$ErrorAction) return $script:fallbackProcess }
function Get-ProcessCommandLine { param([int]$ProcessId) return $null }
function Get-ListeningPid { param([int]$Port) if ($Port -eq 8090) { return 4242 }; return 9999 }
$fallback = @{
    pid = 4242
    service = "api"
    command_identity = "app.main:app"
    project_root = (Get-Location).Path
    port = 8090
    creation_time = "2026-10-28T02:31:21.0000000Z"
}
if (-not (Test-ManagedIdentity -Record $fallback -ProjectRoot (Get-Location).Path)) {
    throw "An exact manifest-matched API listener should be accepted when command-line inspection is denied."
}
$fallback.port = 8091
if (Test-ManagedIdentity -Record $fallback -ProjectRoot (Get-Location).Path) {
    throw "A different listening port PID must be rejected."
}
$fallback.port = 8090
$fallback.project_root = Join-Path (Get-Location).Path "other"
if (Test-ManagedIdentity -Record $fallback -ProjectRoot (Get-Location).Path) {
    throw "A different project root must be rejected."
}
$fallback.project_root = (Get-Location).Path
$fallback.service = "worker"
if (Test-ManagedIdentity -Record $fallback -ProjectRoot (Get-Location).Path) {
    throw "A background worker must not use the port-based ownership fallback."
}
$fallback.service = "api"
$fallback.command_identity = "other:application"
if (Test-ManagedIdentity -Record $fallback -ProjectRoot (Get-Location).Path) {
    throw "A different API command identity must be rejected."
}
$fallback.command_identity = "app.main:app"
$fallback.creation_time = "2026-10-28T02:31:25.0000000Z"
if (Test-ManagedIdentity -Record $fallback -ProjectRoot (Get-Location).Path) {
    throw "A stale process creation timestamp must be rejected."
}

Write-Output "Managed process identity checks passed."
