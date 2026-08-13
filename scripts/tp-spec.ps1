<#
.SYNOPSIS
    Stable TP-Spec-Coding CLI launcher.
.DESCRIPTION
    Resolves Base from TP_SPEC_BASE_ROOT, ~/.tp-spec/installation.yaml, or the
    installed Base script location. The caller working directory is preserved.
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-TpSpecBaseRoot {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    return (
        (Test-Path -LiteralPath (Join-Path $Path 'VERSION') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $Path 'cli\main.py') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $Path 'governance\workflow.yaml') -PathType Leaf)
    )
}

function Get-TpSpecInstallationBaseRoot {
    $configPath = $env:TP_SPEC_INSTALLATION_CONFIG
    if ([string]::IsNullOrWhiteSpace($configPath)) {
        $configPath = Join-Path (Join-Path $HOME '.tp-spec') 'installation.yaml'
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

function Resolve-TpSpecBaseRoot {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:TP_SPEC_BASE_ROOT) { $candidates.Add($env:TP_SPEC_BASE_ROOT) }
    $installed = Get-TpSpecInstallationBaseRoot
    if ($installed) { $candidates.Add($installed) }
    $candidates.Add((Split-Path -Parent $PSScriptRoot))
    foreach ($candidate in $candidates) {
        try { $full = [System.IO.Path]::GetFullPath($candidate) } catch { continue }
        if (Test-TpSpecBaseRoot $full) { return $full }
    }
    return $null
}

$baseRoot = Resolve-TpSpecBaseRoot
if (-not $baseRoot) {
    [Console]::Error.WriteLine('[tp-spec] unable to resolve TP-Spec-Coding root; configure ~/.tp-spec/installation.yaml or set TP_SPEC_BASE_ROOT')
    exit 2
}
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    [Console]::Error.WriteLine('[tp-spec] python executable not found on PATH')
    exit 3
}
$main = Join-Path $baseRoot 'cli\main.py'
& $python.Source $main @Arguments
exit $LASTEXITCODE
