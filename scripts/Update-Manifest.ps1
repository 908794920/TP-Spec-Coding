<#
.SYNOPSIS
Regenerate manifest.sha256 for the actual Git-visible working tree (A-01.1 helper).

.DESCRIPTION
Delegates to scripts/update_manifest.py (UTF-8 byte-safe; PowerShell 5.1
cannot reliably decode git's UTF-8 output for non-ASCII filenames).
Records the SHA-256 of every git-tracked file except the manifest itself
(self-exclusion), UTF-8/LF header included. Deterministic ordering.
#>
[CmdletBinding()]
param(
    [switch]$Verify
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $PSScriptRoot   # tp-spec-base
$py = Join-Path $base 'scripts\update_manifest.py'
if (-not (Test-Path -LiteralPath $py)) { throw "missing $py" }
if ($Verify) {
    & python $py --verify
}
else {
    & python $py
}
exit $LASTEXITCODE
