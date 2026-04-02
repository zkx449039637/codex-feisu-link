[CmdletBinding()]
param(
    [ValidateSet('auto', 'local', 'service')]
    [string]$Mode = 'auto',

    [string]$ConfigPath = $env:CODEX_FEISHU_LINK_CONFIG,

    [string]$PythonExecutable = $env:CODEX_FEISHU_LINK_PYTHON
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Resolve-ConfigFile {
    param(
        [string]$PathFromParameter
    )

    if ($PathFromParameter) {
        return (Resolve-Path -LiteralPath $PathFromParameter).Path
    }

    $candidateNames = @('config.local.json', 'config.json', 'config.example.json')
    foreach ($name in $candidateNames) {
        $candidate = Join-Path -Path $PSScriptRoot -ChildPath $name
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "No config file found. Create config.local.json or run .\init-machine.ps1 to generate one."
}

function Resolve-PythonExecutable {
    param(
        [string]$RequestedPython
    )

    if ($RequestedPython) {
        return $RequestedPython
    }

    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython) {
        return (Resolve-Path -LiteralPath $venvPython).Path
    }

    return 'python'
}

function Read-JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Resolve-Mode {
    param(
        [ValidateSet('auto', 'local', 'service')]
        [string]$RequestedMode,
        [object]$ConfigDocument
    )

    function Test-RealCredentialValue {
        param([object]$Value)

        if ($null -eq $Value) {
            return $false
        }

        $text = [string]$Value
        if ([string]::IsNullOrWhiteSpace($text)) {
            return $false
        }

        $normalized = $text.Trim().ToLowerInvariant()
        return $normalized -notlike '*replace_me*'
    }

    function Test-HasRealFeishuCredentials {
        param([object]$Document)

        $feishu = $Document.feishu
        return $null -ne $feishu -and (Test-RealCredentialValue $feishu.app_id) -and (Test-RealCredentialValue $feishu.app_secret)
    }

    if ($RequestedMode -ne 'auto') {
        if ($RequestedMode -eq 'service' -and -not (Test-HasRealFeishuCredentials -Document $ConfigDocument)) {
            throw "Service mode requires real Feishu credentials. Run .\init-machine.ps1 or edit config.local.json."
        }
        return $RequestedMode
    }

    if (Test-HasRealFeishuCredentials -Document $ConfigDocument) {
        return 'service'
    }

    if ($env:CODEX_FEISHU_LINK_FEISHU_APP_ID -and $env:CODEX_FEISHU_LINK_FEISHU_APP_SECRET) {
        return 'service'
    }

    return 'local'
}

$resolvedConfig = Resolve-ConfigFile -PathFromParameter $ConfigPath
$configDocument = Read-JsonFile -Path $resolvedConfig
$selectedMode = Resolve-Mode -RequestedMode $Mode -ConfigDocument $configDocument

$PythonExecutable = Resolve-PythonExecutable -RequestedPython $PythonExecutable

$env:CODEX_FEISHU_LINK_CONFIG = $resolvedConfig
Write-Host "Starting codex-feishu-link in $selectedMode mode with config $resolvedConfig"
Write-Host "Using Python executable: $PythonExecutable"

# Equivalent Python entrypoint:
# python -m codex_feishu_link --config <config> --mode <mode>
& $PythonExecutable -m codex_feishu_link --config $resolvedConfig --mode $selectedMode
exit $LASTEXITCODE
