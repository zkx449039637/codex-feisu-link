[CmdletBinding()]
param(
    [string]$ConfigPath = $env:CODEX_FEISHU_LINK_CONFIG,
    [string]$PythonExecutable = $env:CODEX_FEISHU_LINK_PYTHON
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Resolve-ServicePaths {
    $serviceRoot = Join-Path $PSScriptRoot '.runtime\service'
    if (-not (Test-Path -LiteralPath $serviceRoot)) {
        New-Item -ItemType Directory -Path $serviceRoot -Force | Out-Null
    }

    return [ordered]@{
        Root = $serviceRoot
        PidFile = Join-Path $serviceRoot 'service.pid'
        StdOutLog = Join-Path $serviceRoot 'service.stdout.log'
        StdErrLog = Join-Path $serviceRoot 'service.stderr.log'
    }
}

function Get-RunningProcess {
    param(
        [string]$PidFile
    )

    if (-not (Test-Path -LiteralPath $PidFile)) {
        return $null
    }

    $rawPid = Get-Content -LiteralPath $PidFile -Raw
    $text = [string]$rawPid
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $null
    }

    $pidValue = 0
    if (-not [int]::TryParse($text.Trim(), [ref]$pidValue)) {
        return $null
    }

    return Get-Process -Id $pidValue -ErrorAction SilentlyContinue
}

$paths = Resolve-ServicePaths
$existing = Get-RunningProcess -PidFile $paths.PidFile
if ($null -ne $existing) {
    Write-Host "codex-feishu-link is already running in background. PID: $($existing.Id)"
    Write-Host "Stdout log: $($paths.StdOutLog)"
    Write-Host "Stderr log: $($paths.StdErrLog)"
    exit 0
}

if (Test-Path -LiteralPath $paths.PidFile) {
    Remove-Item -LiteralPath $paths.PidFile -Force
}

$runServiceScript = Join-Path $PSScriptRoot 'run-service.ps1'
$quotedRunServiceScript = '"' + $runServiceScript + '"'
$argumentList = "-NoProfile -ExecutionPolicy Bypass -File $quotedRunServiceScript -Mode service"

if (-not [string]::IsNullOrWhiteSpace($ConfigPath)) {
    $argumentList += ' -ConfigPath "' + $ConfigPath + '"'
}

if (-not [string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $argumentList += ' -PythonExecutable "' + $PythonExecutable + '"'
}

$process = Start-Process -FilePath 'powershell.exe' `
    -WorkingDirectory $PSScriptRoot `
    -ArgumentList $argumentList `
    -WindowStyle Hidden `
    -RedirectStandardOutput $paths.StdOutLog `
    -RedirectStandardError $paths.StdErrLog `
    -PassThru

Set-Content -LiteralPath $paths.PidFile -Value $process.Id -Encoding ascii

Write-Host "Started codex-feishu-link in background. PID: $($process.Id)"
Write-Host "Stdout log: $($paths.StdOutLog)"
Write-Host "Stderr log: $($paths.StdErrLog)"
