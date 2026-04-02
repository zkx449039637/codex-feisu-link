[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$serviceRoot = Join-Path $PSScriptRoot '.runtime\service'
$pidFile = Join-Path $serviceRoot 'service.pid'
$stdoutLog = Join-Path $serviceRoot 'service.stdout.log'
$stderrLog = Join-Path $serviceRoot 'service.stderr.log'

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host 'Background service is not running.'
    Write-Host "Expected PID file: $pidFile"
    exit 0
}

$rawPid = Get-Content -LiteralPath $pidFile -Raw
$text = [string]$rawPid
$pidValue = 0
if (-not [int]::TryParse($text.Trim(), [ref]$pidValue)) {
    throw "Invalid PID file contents: $text"
}

$process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
if ($null -eq $process) {
    Write-Host "Background service PID file exists, but process $pidValue is not running."
    Write-Host "Stdout log: $stdoutLog"
    Write-Host "Stderr log: $stderrLog"
    exit 1
}

Write-Host "Background service is running."
Write-Host "PID: $pidValue"
Write-Host "Started: $($process.StartTime)"
Write-Host "Stdout log: $stdoutLog"
Write-Host "Stderr log: $stderrLog"
