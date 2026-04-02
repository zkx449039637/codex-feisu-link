[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$serviceRoot = Join-Path $PSScriptRoot '.runtime\service'
$pidFile = Join-Path $serviceRoot 'service.pid'

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host 'No background service PID file was found.'
    exit 0
}

$rawPid = Get-Content -LiteralPath $pidFile -Raw
$text = [string]$rawPid
$pidValue = 0
if (-not [int]::TryParse($text.Trim(), [ref]$pidValue)) {
    Remove-Item -LiteralPath $pidFile -Force
    throw "Invalid PID file contents: $text"
}

$process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
if ($null -eq $process) {
    Remove-Item -LiteralPath $pidFile -Force
    Write-Host "Background service process $pidValue is not running."
    exit 0
}

Stop-Process -Id $pidValue -Force
Remove-Item -LiteralPath $pidFile -Force
Write-Host "Stopped codex-feishu-link background service. PID: $pidValue"
