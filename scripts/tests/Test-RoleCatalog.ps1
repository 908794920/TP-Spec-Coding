<#
.SYNOPSIS
Role Catalog integrity check (read-only).
.DESCRIPTION
Delegates to the deterministic Python validator so PowerShell does not parse
YAML with regexes or hard-code role/state counts.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$validator = Join-Path $base 'scripts\update_role_catalog.py'
if (-not (Test-Path -LiteralPath $validator -PathType Leaf)) { throw "missing $validator" }
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { throw 'python not found on PATH' }
& python $validator --verify
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output 'PASS role_catalog.structured_validator'
exit 0
