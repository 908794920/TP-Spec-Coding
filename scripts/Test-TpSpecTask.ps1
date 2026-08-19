<#
.SYNOPSIS
Thin read-only validator wrapper for a TP-Spec-Coding v5.2.5 Task.

.DESCRIPTION
The Python Record-first runtime is the single source of validation truth. This
PowerShell entry keeps the Windows UX stable without duplicating workflow,
role, evidence, or legacy microstate rules. It never modifies Task data.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateNotNullOrEmpty()]
    [string]$TaskPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-TpSpecBaseRoot {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    return (
        (Test-Path -LiteralPath (Join-Path $Path 'VERSION') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $Path 'cli\main.py') -PathType Leaf)
    )
}

function Resolve-TpSpecBaseRoot {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:TP_SPEC_BASE_ROOT) { $candidates.Add($env:TP_SPEC_BASE_ROOT) }
    $candidates.Add((Split-Path -Parent $PSScriptRoot))
    foreach ($candidate in $candidates) {
        try { $full = [System.IO.Path]::GetFullPath($candidate) } catch { continue }
        if (Test-TpSpecBaseRoot $full) { return $full }
    }
    throw 'TP_SPEC_BASE_ROOT_NOT_FOUND: set TP_SPEC_BASE_ROOT or run from the installed Base.'
}

$fullTaskPath = [System.IO.Path]::GetFullPath($TaskPath)
if (-not (Test-Path -LiteralPath $fullTaskPath -PathType Container)) {
    Write-Error "TASK_DIR_NOT_FOUND: $fullTaskPath"
    exit 4
}

$taskId = Split-Path -Leaf $fullTaskPath
if ([string]::IsNullOrWhiteSpace($taskId)) {
    Write-Error 'TASK_ID_NOT_RESOLVED: task directory basename is empty'
    exit 4
}

$baseRoot = Resolve-TpSpecBaseRoot
$python = $env:TP_SPEC_PYTHON
if ([string]::IsNullOrWhiteSpace($python)) { $python = 'python' }

$oldPythonPath = $env:PYTHONPATH
try {
    if ([string]::IsNullOrWhiteSpace($oldPythonPath)) {
        $env:PYTHONPATH = $baseRoot
    } else {
        $env:PYTHONPATH = "$baseRoot$([System.IO.Path]::PathSeparator)$oldPythonPath"
    }
    & $python -m cli.main task validate --task $taskId --task-dir $fullTaskPath
    exit $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $oldPythonPath
}
