<#
.SYNOPSIS
    Generic TP-Spec-Coding CLI wrapper.
.DESCRIPTION
    Resolves the physical TP-Spec-Coding root from AI_WORK_BASE_ROOT, the user
    installation config (~/.ai-work/installation.yaml), the real Base scripts
    directory, or a legacy project-side scripts Junction. Junction support is
    compatibility-only; new projects do not need project-side Base links.
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-AiWorkBaseRoot {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    return (
        (Test-Path -LiteralPath (Join-Path $Path 'VERSION') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $Path 'cli\main.py') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $Path 'governance\workflow.yaml') -PathType Leaf)
    )
}

function Get-AiWorkInstallationBaseRoot {
    $configPath = $env:AI_WORK_INSTALLATION_CONFIG
    if ([string]::IsNullOrWhiteSpace($configPath)) {
        $configPath = Join-Path (Join-Path $HOME '.ai-work') 'installation.yaml'
    }
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) { return $null }
    try {
        $inBase = $false
        foreach ($line in Get-Content -LiteralPath $configPath -Encoding UTF8) {
            if ($line -match '^base\s*:\s*$') { $inBase = $true; continue }
            if ($line -match '^\S' -and $line -notmatch '^#') { $inBase = $false }
            if ($inBase -and $line -match '^\s+root\s*:\s*(.+?)\s*$') {
                $value = $Matches[1].Trim()
                if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
                if (-not [string]::IsNullOrWhiteSpace($value)) { return $value }
            }
        }
    } catch { }
    return $null
}

function Resolve-AiWorkBaseRoot {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:AI_WORK_BASE_ROOT) { $candidates.Add($env:AI_WORK_BASE_ROOT) }
    $installed = Get-AiWorkInstallationBaseRoot
    if ($installed) { $candidates.Add($installed) }
    $candidates.Add((Split-Path -Parent $PSScriptRoot))

    # Legacy compatibility: if this script itself is reached through a Junction,
    # resolve its target. New project bindings do not require this path.
    try {
        $scriptItem = Get-Item -LiteralPath $PSScriptRoot -Force
        if ($scriptItem.PSObject.Properties.Name -contains 'Target' -and $scriptItem.Target) {
            foreach ($target0 in @($scriptItem.Target)) {
                $target = [string]$target0
                if (-not [System.IO.Path]::IsPathRooted($target)) {
                    $target = Join-Path (Split-Path -Parent $PSScriptRoot) $target
                }
                $candidates.Add((Split-Path -Parent $target))
            }
        }
    } catch { }

    foreach ($candidate in $candidates) {
        try { $full = [System.IO.Path]::GetFullPath($candidate) } catch { continue }
        if (Test-AiWorkBaseRoot $full) { return $full }
    }
    return $null
}

$baseRoot = Resolve-AiWorkBaseRoot
if (-not $baseRoot) {
    [Console]::Error.WriteLine('[ai-work] unable to resolve TP-Spec-Coding root; configure ~/.ai-work/installation.yaml or set AI_WORK_BASE_ROOT')
    exit 2
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    [Console]::Error.WriteLine('[ai-work] python executable not found on PATH')
    exit 3
}

$main = Join-Path $baseRoot 'cli\main.py'
Push-Location -LiteralPath $baseRoot
try {
    & $python.Source $main @Arguments
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code
