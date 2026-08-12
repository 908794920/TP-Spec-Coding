<#
.SYNOPSIS
V5.1.0 single-contract regression: end-to-end 5.1.0 task chain + negative gates.

.DESCRIPTION
Drives a real 5.1.0 task through the CLI (NEW->DEVELOPING->VERIFYING->CLOSING->
COMPLETED) with tool-agnostic tp-* actors, validates it with Test-AiWorkTask.ps1,
and asserts the negative gates (old actor rejected, no direct VERIFYING->COMPLETED,
CLOSING only by tp-delivery-convergence). Delegates the orchestration to
scripts/tests/v510_single_contract.py so the CLI/validator logic is exercised as-is.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)  # ai-work-base
$py = Join-Path $PSScriptRoot 'v510_single_contract.py'
if (-not (Test-Path -LiteralPath $py)) { throw "missing $py" }
Push-Location $base
try {
    & python $py
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}
if ($code -ne 0) {
    Write-Error "V5.1.0 single-contract regression FAILED (exit $code)"
    exit 1
}
Write-Output 'V5.1.0 single-contract regression PASSED'
exit 0
