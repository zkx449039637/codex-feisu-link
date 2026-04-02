[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$serviceRoot = Join-Path $PSScriptRoot '.runtime\service'
$pidFile = Join-Path $serviceRoot 'service.pid'

$targets = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and
    $null -ne $_.CommandLine -and
    $_.CommandLine -match 'codex_feishu_link'
}

if (-not $targets) {
    if (Test-Path -LiteralPath $pidFile) {
        Remove-Item -LiteralPath $pidFile -Force
    }
    Write-Host 'No codex-feishu-link processes are running on this machine.'
    exit 0
}

$stopped = @()
foreach ($target in $targets) {
    try {
        Stop-Process -Id $target.ProcessId -Force -ErrorAction Stop
        $stopped += $target.ProcessId
        Write-Host "Stopped codex-feishu-link process PID: $($target.ProcessId)"
    } catch {
        Write-Warning "Failed to stop PID $($target.ProcessId): $($_.Exception.Message)"
    }
}

if (Test-Path -LiteralPath $pidFile) {
    Remove-Item -LiteralPath $pidFile -Force
}

if ($stopped.Count -eq 0) {
    Write-Host 'No codex-feishu-link processes were stopped.'
    exit 1
}

Write-Host "Stopped $($stopped.Count) codex-feishu-link process(es)."
