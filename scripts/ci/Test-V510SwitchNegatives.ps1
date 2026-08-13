<#
.SYNOPSIS
V5.1.0 switch negatives: prove the 9.9.9 contract is now rejected (plan 搂8 P3).

.DESCRIPTION
After the 9.9.9 -> 5.1.0 active-contract switch, a task declaring
artifact_contract.version 9.9.9 must be rejected at two layers, while a 5.1.0
task is accepted by the outer gate:

  N1 validator : Test-TpSpecTask.ps1 must reject a 9.9.9 status.yaml with
                 LEGACY_CONTRACT_REJECTED (non-zero exit).
  N2 gate      : `tp-spec config gate --task-version 9.9.9` must fail with
                 VERSION_MISMATCH (exit code 14).
  N3 gate pos  : `tp-spec config gate --task-version 5.1.0` must be accepted
                 (exit 0), confirming the switch is live.

All work happens in a self-created temp directory. Fully offline. Exit 0 only
if every assertion holds.
#>
[CmdletBinding()]
param([switch]$KeepWorkDir)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$base = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # tp-spec-base
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$script:failures = 0
function Check([string]$Name, [bool]$Ok, [string]$Detail = '') {
    if ($Ok) { Write-Output "PASS $Name $Detail" }
    else { Write-Output "FAIL $Name $Detail"; $script:failures++ }
}

$pyCmd = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not (Test-Path -LiteralPath $pyCmd)) { throw 'python not found; offline prerequisite missing (fail, not skip)' }

$workDir = Join-Path ([System.IO.Path]::GetTempPath()) ("tpspec-switchneg-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $workDir -Force | Out-Null
Write-Output "WORKDIR $workDir"

function Invoke-Child([string]$File, [string[]]$ArgumentList, [string]$LogName) {
    $log = Join-Path $workDir $LogName
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & powershell -NoProfile -ExecutionPolicy Bypass -File $File @ArgumentList *> $log
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    return @{ Code = $code; Log = $log }
}

try {
    # N1: a 9.9.9 task must be rejected by the validator as legacy contract
    $taskDir = Join-Path $workDir 'TASK-SWITCH-0505'
    New-Item -ItemType Directory -Path $taskDir -Force | Out-Null
    $statusYaml = @(
        'task_id: TASK-SWITCH-0505'
        'artifact_contract:'
        '  version: "9.9.9"'
        'current_state: DEVELOPING'
        'current_owner: tp-development-engineering'
    ) -join "`n"
    [System.IO.File]::WriteAllText((Join-Path $taskDir 'status.yaml'), $statusYaml + "`n", $utf8NoBom)
    $r1 = Invoke-Child (Join-Path $base 'scripts\Test-TpSpecTask.ps1') @($taskDir) 'n1-validator.log'
    $n1Hit = Select-String -LiteralPath $r1.Log -Pattern 'LEGACY_CONTRACT_REJECTED' -Quiet
    Check 'N1.validator.legacy_9.9.9_rejected' (($r1.Code -ne 0) -and $n1Hit) "exit=$($r1.Code) LEGACY_CONTRACT_REJECTED=$n1Hit"

    # N2: the outer contract gate must reject task-version 9.9.9 with VERSION_MISMATCH (exit 14)
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    & $pyCmd (Join-Path $base 'cli\main.py') config gate --task-version 9.9.9 --base-root $base *> (Join-Path $workDir 'n2-gate.log')
    $n2Code = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    $n2Hit = Select-String -LiteralPath (Join-Path $workDir 'n2-gate.log') -Pattern 'VERSION_MISMATCH' -Quiet
    Check 'N2.gate.9.9.9_version_mismatch_exit14' (($n2Code -eq 14) -and $n2Hit) "exit=$n2Code VERSION_MISMATCH=$n2Hit"

    # N3: the outer contract gate must accept task-version 5.1.0 (exit 0)
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    & $pyCmd (Join-Path $base 'cli\main.py') config gate --task-version 5.1.0 --base-root $base *> (Join-Path $workDir 'n3-gate.log')
    $n3Code = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    Check 'N3.gate.5.1.0_accepted' ($n3Code -eq 0) "exit=$n3Code"

    # hygiene: never leave bytecode residue
    Get-ChildItem -LiteralPath (Join-Path $base 'cli') -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

    if ($script:failures -gt 0) {
        Write-Output "SWITCH-NEGATIVE SUITE FAILED ($script:failures failure(s))"
        exit 1
    }
    Write-Output 'SWITCH-NEGATIVE SUITE PASSED (9.9.9 rejected, 5.1.0 accepted)'
    exit 0
}
finally {
    if (-not $KeepWorkDir) {
        $resolved = Resolve-Path -LiteralPath $workDir -ErrorAction SilentlyContinue
        if ($resolved -and (Split-Path -Leaf $resolved.Path).StartsWith('tpspec-switchneg-')) {
            Remove-Item -LiteralPath $resolved.Path -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    else { Write-Output "KEPT $workDir" }
}
