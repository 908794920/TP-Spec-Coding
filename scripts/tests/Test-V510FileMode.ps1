<#
.SYNOPSIS
V5.1.0 file-mode isolated end-to-end regression through Invoke-AiWorkHandoffFlush.ps1.

.DESCRIPTION
Creates an isolated 5.1.0 L1 task under the system temp directory (never a real
project) and drives the full chain NEW -> DEVELOPING -> VERIFYING -> CLOSING ->
COMPLETED by actually invoking scripts/Invoke-AiWorkHandoffFlush.ps1 with tp-*
actors. It also proves the ai-work.ps1 non-DB path delegates to the flush.

Because file-mode flush always transitions, the no-transition review record
(the file-mode analogue of `ai-work commit --review-only`) is written directly
as a genuine tp-verification-engineering REVIEW_COMPLETED PASS event that matches
codex-review.md; the CLOSING flush still fully enforces the closing chain against
it. No validator or workflow rule is relaxed.

Asserts: old actor rejected, direct VERIFYING->COMPLETED rejected, non-delivery
CLOSING rejected, final Test-AiWorkTask.ps1 returns 0 errors, status/events/
generated projections and handoff consumption are correct, and a flush replay of
the already-consumed handoff is a successful no-op that appends no duplicate STATE.
The temp directory is kept for audit. Exit code is non-zero on any failure.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)  # ai-work-base
$flush = Join-Path $base 'scripts\Invoke-AiWorkHandoffFlush.ps1'
$aiwork = Join-Path $base 'scripts\ai-work.ps1'
$validator = Join-Path $base 'scripts\Test-AiWorkTask.ps1'
$tpl = Join-Path $base 'templates\5.1.3'
$utf8 = New-Object System.Text.UTF8Encoding($false)

$script:Results = @()
function Check([string]$Name, [bool]$Ok, [string]$Detail = '') {
    $script:Results += [pscustomobject]@{ Name = $Name; Ok = $Ok; Detail = $Detail }
    if ($Ok) { Write-Output "PASS $Name $Detail" } else { Write-Output "FAIL $Name $Detail" }
}

function Write-Text([string]$Path, [string]$Text) {
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($Path, $Text, $utf8)
}

# --- isolated temp project (never a real task) ---
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("v510filemode-" + [guid]::NewGuid().ToString('N'))
$taskId = 'TASK-20260730-701'
$taskDir = Join-Path $work ".ai-work\tasks\$taskId"
New-Item -ItemType Directory -Path $taskDir -Force | Out-Null

function New-TaskCopy([string]$dir, [string]$tid, [string]$state = 'NEW', [string]$owner = 'tp-architecture-design') {
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    foreach ($f in (Get-ChildItem -LiteralPath $tpl -File)) {
        Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $dir $f.Name) -Force
    }
    $sp = Join-Path $dir 'status.yaml'
    $s = [System.IO.File]::ReadAllText($sp, $utf8)
    $s = $s.Replace('task_id: "TASK-YYYYMMDD-XXX"', "task_id: `"$tid`"").Replace('created: "YYYY-MM-DD"', 'created: "2026-07-30"')
    $s = [regex]::Replace($s, '(?m)^current_state:\s*.*$', "current_state: `"$state`"")
    $s = [regex]::Replace($s, '(?m)^current_owner:\s*.*$', "current_owner: `"$owner`"")
    Write-Text $sp $s
    # acceptance AC-01 PASS + evidence
    $ap = Join-Path $dir 'acceptance.md'
    $a = [System.IO.File]::ReadAllText($ap, $utf8)
    $a = $a.Replace('| AC-01 |  | `task.md` |  |  |  |  | PENDING |',
                    '| AC-01 | 基础功能可用 | `task.md` | L1 | 非浏览器验证 | evidence/ac01.md | none | PASS |')
    Write-Text $ap $a
    Write-Text (Join-Path $dir 'evidence\ac01.md') "ac01 evidence`n"
    Write-Text (Join-Path $dir 'events.jsonl') ''
}

function Set-ImplReady([string]$dir) {
    $p = Join-Path $dir 'implementation.md'
    $t = [System.IO.File]::ReadAllText($p, $utf8)
    $t = $t.Replace('  status: "draft"', '  status: "ready"')
    Write-Text $p $t
}

function Set-ReviewPass([string]$dir, [string]$intendedNext, [string]$evidence, [string]$timestamp) {
    $p = Join-Path $dir 'codex-review.md'
    $t = [System.IO.File]::ReadAllText($p, $utf8)
    $t = $t.Replace('  decision: "PENDING"', '  decision: "PASS"')
    $t = $t.Replace('  evidence: ""', "  evidence: `"$evidence`"")
    $t = $t.Replace('  timestamp: ""', "  timestamp: `"$timestamp`"")
    $t = $t.Replace('  intended_next: ""', "  intended_next: `"$intendedNext`"")
    Write-Text $p $t
}

function Get-NextEventId([string]$dir) {
    $ev = Join-Path $dir 'events.jsonl'
    $max = 0
    foreach ($ln in (Get-Content -LiteralPath $ev -Encoding UTF8 -ErrorAction SilentlyContinue)) {
        if ($ln -match '"id"\s*:\s*"E-(\d+)"') { $n = [int]$Matches[1]; if ($n -gt $max) { $max = $n } }
    }
    return $max + 1
}

function Get-LastEventTime([string]$dir) {
    $ev = Join-Path $dir 'events.jsonl'
    $t = $null
    foreach ($ln in (Get-Content -LiteralPath $ev -Encoding UTF8 -ErrorAction SilentlyContinue)) {
        if ($ln -match '"time"\s*:\s*"([^"]+)"') { $t = $Matches[1] }
    }
    if ($null -eq $t) { $t = (Get-Date).ToString('o') }
    return $t
}

# build a full V5.1.0 handoff.json (unconsumed) for the given transition
function Write-Handoff([string]$dir, [string]$tid, [string]$actor, [string]$summary, [string]$nextState, [string]$nextOwner, [hashtable]$human = $null) {
    $np = [ordered]@{
        target_role           = $nextOwner
        invocation            = "/$nextOwner 接续 $tid"
        task_id               = $tid
        target_state          = $nextState
        risk_level            = 'L1'
        page_verification     = 'NOT_REQUIRED'
        entry                 = 'generated/continuation.md'
        reading_order         = @('status.yaml', 'task.md', 'acceptance.md')
        actions               = @('接续本阶段并按契约推进')
        constraints           = @('仅在批准范围内修改；事实以账本为准')
        exit_expectation      = "完成 $nextState 阶段并交接"
        fact_source_disclaimer = '本提示不是事实来源；以 status.yaml/events.jsonl/阶段工件为准。'
    }
    $h = [ordered]@{
        schema_version = '5.1.0'
        handoff_id     = 'H-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
        flush_id       = ''
        consumed       = $false
        actor          = $actor
        summary        = $summary
        changes        = @()
        risks          = @()
        evidence       = @('handoff.json')
        next           = [ordered]@{ state = $nextState; owner = $nextOwner }
        next_prompt    = $np
    }
    if ($null -ne $human) { $h['human_confirmation'] = $human }
    Write-Text (Join-Path $dir 'handoff.json') ($h | ConvertTo-Json -Depth 12)
}

function Invoke-Flush([string]$dir, [string]$actor, [switch]$ReviewOnly) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        $args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $flush, '-TaskPath', $dir, '-Actor', $actor)
        if ($ReviewOnly) { $args += '-ReviewOnly' }
        $out = & powershell.exe @args 2>&1 | Out-String
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $prev }
    return @{ Code = $code; Out = $out }
}

function Invoke-AiWork([string]$dir, [string]$actor) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $aiwork -TaskPath $dir -Actor $actor 2>&1 | Out-String
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $prev }
    return @{ Code = $code; Out = $out }
}

function Get-StateCount([string]$dir) {
    $ev = Join-Path $dir 'events.jsonl'
    return @(Get-Content -LiteralPath $ev -Encoding UTF8 | Where-Object { $_ -match '"type"\s*:\s*"STATE"' }).Count
}

# ============================ happy path ============================
New-TaskCopy $taskDir $taskId 'NEW' 'tp-architecture-design'

# 1. NEW -> DEVELOPING (tp-architecture-design)
Write-Handoff $taskDir $taskId 'tp-architecture-design' 'risk L1 -> dev' 'DEVELOPING' 'tp-development-engineering'
$r = Invoke-Flush $taskDir 'tp-architecture-design'
Check 'flush_NEW_DEVELOPING_rc0' ($r.Code -eq 0) "rc=$($r.Code)"

# 2. DEVELOPING -> VERIFYING (tp-development-engineering); implementation.md ready
Set-ImplReady $taskDir
Write-Handoff $taskDir $taskId 'tp-development-engineering' 'impl done' 'VERIFYING' 'tp-verification-engineering'
$r = Invoke-Flush $taskDir 'tp-development-engineering'
Check 'flush_DEV_VERIFYING_rc0' ($r.Code -eq 0) "rc=$($r.Code)"

# 3. Record the no-transition review through the formal file-mode entry.
$reviewTime = Get-LastEventTime $taskDir
Set-ReviewPass $taskDir 'CLOSING' 'evidence/ac01.md' $reviewTime
$beforeReviewStates = Get-StateCount $taskDir
$r = Invoke-Flush $taskDir 'tp-verification-engineering' -ReviewOnly
$afterReviewStates = Get-StateCount $taskDir
Check 'flush_review_only_rc0' ($r.Code -eq 0) "rc=$($r.Code)"
Check 'review_only_no_state_transition' ($afterReviewStates -eq $beforeReviewStates) "before=$beforeReviewStates after=$afterReviewStates"
$evPath = Join-Path $taskDir 'events.jsonl'
Check 'review_only_event_recorded' (@(Get-Content -LiteralPath $evPath -Encoding UTF8 | Where-Object { $_ -match '"type"\s*:\s*"REVIEW_COMPLETED"' -and $_ -match '"actor"\s*:\s*"tp-verification-engineering"' -and $_ -match '"decision"\s*:\s*"PASS"' }).Count -eq 1) 'formal REVIEW_COMPLETED PASS recorded'

# 4. VERIFYING -> CLOSING (tp-delivery-convergence)
Write-Handoff $taskDir $taskId 'tp-delivery-convergence' 'closing' 'CLOSING' 'tp-delivery-convergence'
$r = Invoke-Flush $taskDir 'tp-delivery-convergence'
Check 'flush_VERIFYING_CLOSING_rc0' ($r.Code -eq 0) "rc=$($r.Code) $($r.Out.Split([char]10) | Select-Object -Last 1)"

# 5. CLOSING -> COMPLETED (tp-delivery-convergence)
Write-Handoff $taskDir $taskId 'tp-delivery-convergence' 'completed' 'COMPLETED' 'tp-delivery-convergence'
$r = Invoke-Flush $taskDir 'tp-delivery-convergence'
Check 'flush_CLOSING_COMPLETED_rc0' ($r.Code -eq 0) "rc=$($r.Code) $($r.Out.Split([char]10) | Select-Object -Last 1)"

# 6. validator must return 0 errors at COMPLETED
$vout = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $validator -TaskPath $taskDir 2>&1
$vcode = $LASTEXITCODE
$vdetail = if ($vcode -ne 0) { ($vout -join "`n") } else { '' }
Check 'validator_completed_0errors' ($vcode -eq 0) $vdetail

# 7. projection / consumption assertions
$statusText = [System.IO.File]::ReadAllText((Join-Path $taskDir 'status.yaml'), $utf8)
Check 'status_state_completed' ($statusText -match '(?m)^current_state:\s*"COMPLETED"') ''
Check 'status_owner_delivery' ($statusText -match '(?m)^current_owner:\s*"tp-delivery-convergence"') ''
$evAll = Get-Content -LiteralPath (Join-Path $taskDir 'events.jsonl') -Encoding UTF8
Check 'events_has_state_completed' (@($evAll | Where-Object { $_ -match '"type"\s*:\s*"STATE"' -and $_ -match '"state"\s*:\s*"COMPLETED"' }).Count -ge 1) ''
Check 'events_has_review_pass' (@($evAll | Where-Object { $_ -match '"type"\s*:\s*"REVIEW_COMPLETED"' -and $_ -match '"decision"\s*:\s*"PASS"' }).Count -ge 1) ''
Check 'generated_final_result_exists' (Test-Path -LiteralPath (Join-Path $taskDir 'generated\final-result.md')) ''
Check 'generated_continuation_exists' (Test-Path -LiteralPath (Join-Path $taskDir 'generated\continuation.md')) ''
$hoText = [System.IO.File]::ReadAllText((Join-Path $taskDir 'handoff.json'), $utf8)
$ho = $hoText | ConvertFrom-Json
Check 'handoff_consumed_true' ([bool]$ho.consumed -eq $true -and -not [string]::IsNullOrWhiteSpace([string]$ho.flush_id)) ''

# 8. replay the already-consumed COMPLETED handoff: successful no-op, no duplicate STATE
$beforeStates = Get-StateCount $taskDir
$r = Invoke-Flush $taskDir 'tp-delivery-convergence'
$afterStates = Get-StateCount $taskDir
Check 'replay_flush_rc0' ($r.Code -eq 0) "rc=$($r.Code)"
Check 'replay_no_duplicate_state' ($afterStates -eq $beforeStates) "before=$beforeStates after=$afterStates"

# 8b. ai-work.ps1 non-DB path delegates to flush (no registry/DB -> passthrough), replay no-op
$r = Invoke-AiWork $taskDir 'tp-delivery-convergence'
$afterWrap = Get-StateCount $taskDir
Check 'aiwork_nondb_delegates_flush_rc0' ($r.Code -eq 0) "rc=$($r.Code)"
Check 'aiwork_nondb_no_duplicate_state' ($afterWrap -eq $beforeStates) "before=$beforeStates after=$afterWrap"

# ============================ negatives ============================
# N1: old/unknown actor rejected by flush -Actor ValidateSet (represents any legacy actor)
$ndir = Join-Path $work ".ai-work\tasks\TASK-20260730-711"
New-TaskCopy $ndir 'TASK-20260730-711' 'NEW' 'tp-architecture-design'
Write-Handoff $ndir 'TASK-20260730-711' 'tp-architecture-design' 'x' 'DEVELOPING' 'tp-development-engineering'
$r = Invoke-Flush $ndir 'legacy-tool-actor'
Check 'neg_old_actor_rejected' ($r.Code -ne 0) "rc=$($r.Code)"

# N2: direct VERIFYING -> COMPLETED rejected (no valid transition / must come from CLOSING)
$ndir2 = Join-Path $work ".ai-work\tasks\TASK-20260730-712"
New-TaskCopy $ndir2 'TASK-20260730-712' 'VERIFYING' 'tp-verification-engineering'
Write-Handoff $ndir2 'TASK-20260730-712' 'tp-delivery-convergence' 'x' 'COMPLETED' 'tp-delivery-convergence'
$r = Invoke-Flush $ndir2 'tp-delivery-convergence'
Check 'neg_verifying_to_completed_rejected' ($r.Code -ne 0) "rc=$($r.Code)"

# N3: non-delivery actor cannot enter CLOSING (SHD satisfied so the closing-chain actor rule is exercised)
$ndir3 = Join-Path $work ".ai-work\tasks\TASK-20260730-713"
New-TaskCopy $ndir3 'TASK-20260730-713' 'VERIFYING' 'tp-verification-engineering'
Set-ReviewPass $ndir3 'CLOSING' 'evidence/ac01.md' ((Get-Date).ToString('o'))
Write-Handoff $ndir3 'TASK-20260730-713' 'tp-development-engineering' 'x' 'CLOSING' 'tp-delivery-convergence'
$r = Invoke-Flush $ndir3 'tp-development-engineering'
Check 'neg_nondelivery_closing_rejected' ($r.Code -ne 0) "rc=$($r.Code)"

# ============================ summary ============================
$failed = @($script:Results | Where-Object { -not $_.Ok })
Write-Output ''
Write-Output '=== SUMMARY ==='
Write-Output ("total={0} passed={1} failed={2}" -f $script:Results.Count, ($script:Results.Count - $failed.Count), $failed.Count)
Write-Output "WORKDIR $work"
if ($failed.Count -gt 0) {
    Write-Output ("FAILED: " + (($failed | ForEach-Object { $_.Name }) -join ', '))
    exit 1
}
Write-Output 'V5.1.0 file-mode regression PASSED'
exit 0
