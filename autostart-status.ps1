[CmdletBinding()]
param(
    [string]$TaskName = 'CodexFeishuLink'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$task = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -eq $TaskName } | Select-Object -First 1
if ($null -eq $task) {
    Write-Host "Scheduled task $TaskName is not registered."
    exit 0
}

$info = Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath

Write-Host "Scheduled task is registered."
Write-Host "Task name: $TaskName"
Write-Host "State: $($task.State)"
Write-Host "Last run time: $($info.LastRunTime)"
Write-Host "Last task result: $($info.LastTaskResult)"
Write-Host "Next run time: $($info.NextRunTime)"
