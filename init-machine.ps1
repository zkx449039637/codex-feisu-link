[CmdletBinding()]
param(
    [string]$TemplatePath = (Join-Path $PSScriptRoot 'machine.template.json'),
    [string]$OutputPath = (Join-Path $PSScriptRoot 'config.local.json'),
    [switch]$Force,
    [string]$MachineName = $env:COMPUTERNAME,
    [string]$PythonExecutable = $env:CODEX_FEISHU_LINK_PYTHON,
    [string]$CodexExecutable = $env:CODEX_FEISHU_LINK_CODEX_EXECUTABLE,
    [string]$CodexScript,
    [string[]]$ProjectPath = @(),
    [string[]]$ProjectName = @(),
    [string]$BotAppId = $env:CODEX_FEISHU_LINK_FEISHU_APP_ID,
    [string]$BotAppSecret = $env:CODEX_FEISHU_LINK_FEISHU_APP_SECRET,
    [string[]]$AllowedUserIds = @(),
    [string]$AllowedUserIdsCsv = $env:CODEX_FEISHU_LINK_ALLOWED_USER_IDS,
    [string]$BaseUrl = 'https://open.feishu.cn',
    [ValidateSet('chat_id', 'sender_id')]
    [string]$ReceiveIdType = 'chat_id'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Read-JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Test-PlaceholderValue {
    param(
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $true
    }

    $normalized = $Value.Trim().ToLowerInvariant()
    return $normalized -eq 'replace_me' -or $normalized -eq 'cli_replace_me'
}

function Convert-ToStringArray {
    param(
        [object]$Value
    )

    if ($null -eq $Value) {
        return @()
    }

    if ($Value -is [string]) {
        if ([string]::IsNullOrWhiteSpace($Value)) {
            return @()
        }
        return @($Value)
    }

    if ($Value -is [System.Collections.IEnumerable]) {
        $items = @()
        foreach ($item in $Value) {
            if (-not [string]::IsNullOrWhiteSpace([string]$item)) {
                $items += [string]$item
            }
        }
        return $items
    }

    return @([string]$Value)
}

if (-not (Test-Path -LiteralPath $TemplatePath)) {
    throw "Template file not found: $TemplatePath"
}

if ((Test-Path -LiteralPath $OutputPath) -and -not $Force) {
    throw "Output file already exists: $OutputPath. Use -Force to overwrite it."
}

$template = Read-JsonFile -Path $TemplatePath
$repoRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$stateRoot = Join-Path $repoRoot '.state'
$runtimeRoot = Join-Path $repoRoot '.runtime'
$runtimeStateFile = Join-Path $runtimeRoot 'runtime-state.json'
$runtimeLogDir = Join-Path $runtimeRoot 'logs'
$runtimeArtifactDir = Join-Path $runtimeRoot 'artifacts'

if (-not $PythonExecutable) {
    $PythonExecutable = 'python'
}

if (-not $CodexScript) {
    $CodexScript = Join-Path $repoRoot 'node_modules\@openai\codex\bin\codex.js'
}

if (-not $CodexExecutable) {
    if (Test-Path -LiteralPath $CodexScript) {
        $CodexExecutable = 'node'
    } else {
        $CodexExecutable = 'codex'
    }
}

$resolvedCodexArguments = @()
if ($CodexExecutable -eq 'node' -and (Test-Path -LiteralPath $CodexScript)) {
    $resolvedCodexArguments = @($CodexScript)
}

$AllowedUserIds = @(Convert-ToStringArray $AllowedUserIds)
$ProjectPath = @(Convert-ToStringArray $ProjectPath)
$ProjectName = @(Convert-ToStringArray $ProjectName)

if ($AllowedUserIds.Count -eq 0 -and -not [string]::IsNullOrWhiteSpace($AllowedUserIdsCsv)) {
    $AllowedUserIds = $AllowedUserIdsCsv.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ }
}

if ($ProjectPath.Count -eq 0) {
    $ProjectPath = @($repoRoot)
}

$resolvedProjects = [ordered]@{}
$projectEntries = @()
foreach ($property in $template.projects.PSObject.Properties) {
    $projectEntries += $property
}

for ($i = 0; $i -lt $projectEntries.Count; $i++) {
    $property = $projectEntries[$i]
    $source = $property.Value

    $name = if ($i -lt $ProjectName.Count -and -not [string]::IsNullOrWhiteSpace($ProjectName[$i])) {
        $ProjectName[$i]
    } elseif ($source.name -and -not (Test-PlaceholderValue -Value ([string]$source.name))) {
        [string]$source.name
    } else {
        $property.Name
    }

    $workdir = if ($i -lt $ProjectPath.Count -and -not [string]::IsNullOrWhiteSpace($ProjectPath[$i])) {
        (Resolve-Path -LiteralPath $ProjectPath[$i]).Path
    } elseif ($source.workdir -and -not (Test-PlaceholderValue -Value ([string]$source.workdir))) {
        [string]$source.workdir
    } else {
        $repoRoot
    }

    $resolvedProjects[$name] = [ordered]@{
        name = $name
        workdir = $workdir
        branch_prefix = if ($source.branch_prefix) { [string]$source.branch_prefix } else { 'codex/' }
        description = if ($source.description) { [string]$source.description } else { 'Remote-controlled local Codex project.' }
        max_parallel_tasks = if ($source.max_parallel_tasks) { [int]$source.max_parallel_tasks } else { 1 }
    }
}

if ([string]::IsNullOrWhiteSpace($BotAppId) -and $template.bot.app_id) {
    $BotAppId = [string]$template.bot.app_id
}

if ([string]::IsNullOrWhiteSpace($BotAppSecret) -and $template.bot.app_secret) {
    $BotAppSecret = [string]$template.bot.app_secret
}

if ($AllowedUserIds.Count -eq 0 -and $template.bot.allowed_user_ids) {
    $AllowedUserIds = Convert-ToStringArray $template.bot.allowed_user_ids | Where-Object { -not (Test-PlaceholderValue -Value $_) }
}

$AllowedUserIds = @($AllowedUserIds | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })

$config = [ordered]@{
    machine = [ordered]@{
        name = if ([string]::IsNullOrWhiteSpace($MachineName)) { $env:COMPUTERNAME } else { $MachineName }
        repo_root = $repoRoot
        python_executable = $PythonExecutable
        codex_executable = $CodexExecutable
        codex_script = $CodexScript
    }
    bot = [ordered]@{
        app_id = if ([string]::IsNullOrWhiteSpace($BotAppId)) { 'replace_me' } else { $BotAppId }
        app_secret = if ([string]::IsNullOrWhiteSpace($BotAppSecret)) { 'replace_me' } else { $BotAppSecret }
        base_url = $BaseUrl
        receive_id_type = $ReceiveIdType
        allowed_user_ids = [string[]]$AllowedUserIds
    }
    state_file = (Join-Path $stateRoot 'state.json')
    runtime_root = $runtimeRoot
    runtime_state_file = $runtimeStateFile
    runtime_log_dir = $runtimeLogDir
    runtime_artifact_dir = $runtimeArtifactDir
    codex_executable = $CodexExecutable
    codex_arguments = @($resolvedCodexArguments)
    command_timeout_seconds = 600
    runtime_poll_interval_seconds = 2.0
    feishu = [ordered]@{
        app_id = if ([string]::IsNullOrWhiteSpace($BotAppId)) { 'replace_me' } else { $BotAppId }
        app_secret = if ([string]::IsNullOrWhiteSpace($BotAppSecret)) { 'replace_me' } else { $BotAppSecret }
        base_url = $BaseUrl
        receive_id_type = $ReceiveIdType
        allowed_user_ids = [string[]]$AllowedUserIds
    }
    projects = $resolvedProjects
}

$configJson = $config | ConvertTo-Json -Depth 20
$destinationDir = Split-Path -Parent $OutputPath
if ($destinationDir -and -not (Test-Path -LiteralPath $destinationDir)) {
    New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
}

[System.IO.File]::WriteAllText($OutputPath, $configJson + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

$missing = @()
if (Test-PlaceholderValue -Value $config.feishu.app_id) {
    $missing += 'feishu.app_id'
}
if (Test-PlaceholderValue -Value $config.feishu.app_secret) {
    $missing += 'feishu.app_secret'
}
if ($config.feishu.allowed_user_ids.Count -eq 0) {
    $missing += 'feishu.allowed_user_ids'
}
foreach ($entry in $config.projects.GetEnumerator()) {
    if (Test-PlaceholderValue -Value $entry.Value.workdir) {
        $missing += "projects.$($entry.Key).workdir"
    }
}

Write-Host "Created $OutputPath from $TemplatePath"
Write-Host "Machine: $($config.machine.name)"
Write-Host "Codex: $($config.codex_executable) $($config.codex_arguments -join ' ')"

if ($missing.Count -gt 0) {
    Write-Host "Remaining values to fill:"
    foreach ($item in ($missing | Select-Object -Unique)) {
        Write-Host " - $item"
    }
} else {
    Write-Host "All required placeholders were filled."
}
