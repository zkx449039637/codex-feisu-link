[CmdletBinding()]
param(
    [string]$TaskName = 'CodexFeishuLink',
    [string]$ConfigPath = $env:CODEX_FEISHU_LINK_CONFIG,
    [string]$PythonExecutable = $env:CODEX_FEISHU_LINK_PYTHON
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$startScript = Join-Path $PSScriptRoot 'start-background.ps1'
$arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $startScript + '"'

if (-not [string]::IsNullOrWhiteSpace($ConfigPath)) {
    $arguments += ' -ConfigPath "' + $ConfigPath + '"'
}

if (-not [string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $arguments += ' -PythonExecutable "' + $PythonExecutable + '"'
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Start codex-feishu-link in background at user logon.' `
    -Force | Out-Null

Write-Host "Registered auto-start scheduled task: $TaskName"
