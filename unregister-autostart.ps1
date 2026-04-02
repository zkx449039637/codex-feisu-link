[CmdletBinding()]
param(
    [string]$TaskName = 'CodexFeishuLink'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "Scheduled task $TaskName does not exist."
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed auto-start scheduled task: $TaskName"
