<#
.SYNOPSIS
V5.1.0 DB-backend guard regression for Invoke-TpSpecHandoffFlush.ps1 (isolated).

.DESCRIPTION
Regression for the 2026-07-30 bug fix: when the DB backend is enabled, calling
the low-level flush directly must be rejected (non-zero exit, actionable
guidance, zero side effects), because a direct call skips projection rebuild
and event sync and silently leaves the SQLite ledger behind (TASK-21956).

Builds an isolated temp project with its own SQLite ledger and a temp
registry.local.json (wired through TP_SPEC_REGISTRY), then asserts:
  S1  DB enabled + direct flush        -> rejected, file/DB state unchanged,
      no .flush-journal residue (true zero side effects)
  S2  DB enabled + tp-spec.ps1 wrapper -> file projection and SQLite task
      state/owner consistent (rebuild -> flush -> sync)
  S4  event sync retried               -> idempotent, no duplicate flush_id
      events, task row stable
  S3  DB not enabled (task in no ledger) + direct flush -> original file-mode
      behavior preserved (exit 0, state advanced, no guard message)
  S5  detection cannot produce a trusted verdict (corrupt ledger via
      TP_SPEC_DB) + direct flush -> rejected fail-closed, zero side effects
  S6  DB actually enabled but tp-spec.ps1 detection cannot produce a trusted
      verdict (corrupt ledger via TP_SPEC_DB) -> wrapper rejects fail-closed
      (exit 9), no rebuild/flush/sync, file and SQLite state untouched

Never touches real projects or production Runtime databases. The temp directory is kept
for audit. Exit code is non-zero on any failure.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)  # tp-spec-base
$flush = Join-Path $base 'scripts\Invoke-TpSpecHandoffFlush.ps1'
$tpspec = Join-Path $base 'scripts\tp-spec.ps1'
$cliMain = Join-Path $base 'cli\main.py'
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

# --- isolated temp project + ledger (never a real task) ---
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("v510dbguard-" + [guid]::NewGuid().ToString('N'))
$projRoot = Join-Path $work 'proj'
$taskId = 'TASK-20260730-801'
$taskDir = Join-Path $projRoot ".tp-spec\tasks\$taskId"
$dbPath = Join-Path $projRoot ".tp-spec\db\guard.db"
$registryPath = Join-Path $work 'registry.local.json'
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

# build a full V5.1.0 handoff.json (unconsumed) for the given transition
function Write-Handoff([string]$dir, [string]$tid, [string]$actor, [string]$summary, [string]$nextState, [string]$nextOwner) {
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
    Write-Text (Join-Path $dir 'handoff.json') ($h | ConvertTo-Json -Depth 12)
}

function Invoke-Flush([string]$dir, [string]$actor) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $flush -TaskPath $dir -Actor $actor 2>&1 | Out-String
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $prev }
    return @{ Code = $code; Out = $out }
}

function Invoke-TpSpec([string]$dir, [string]$actor) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $tpspec -TaskPath $dir -Actor $actor 2>&1 | Out-String
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $prev }
    return @{ Code = $code; Out = $out }
}

function Invoke-Python([string]$Code) {
    $f = Join-Path ([System.IO.Path]::GetTempPath()) ('dbguard-' + [guid]::NewGuid().ToString('N') + '.py')
    [System.IO.File]::WriteAllText($f, $Code, $utf8)
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        $out = & python $f 2>&1 | Out-String
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prev
        Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue
    }
    return @{ Code = $code; Out = $out }
}

function Invoke-EventSync([string]$tid, [string]$dir) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        $out = & python $cliMain event sync --task $tid --task-dir $dir 2>&1 | Out-String
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $prev }
    return @{ Code = $code; Out = $out }
}

# query ledger: STATE=..;OWNER=..;EVENTS=n
function Get-LedgerFacts([string]$tid) {
    $q = @"
import sys
sys.path.insert(0, r'$base')
from cli import db as dbmod
conn = dbmod.connect(r'$dbPath')
try:
    row = conn.execute("SELECT current_state, owner_role FROM task WHERE task_id = ?", ('$tid',)).fetchone()
    cnt = conn.execute("SELECT COUNT(*) AS c FROM task_event WHERE task_id = ?", ('$tid',)).fetchone()['c']
    print('STATE=%s;OWNER=%s;EVENTS=%s' % (row['current_state'], row['owner_role'], cnt))
finally:
    conn.close()
"@
    $r = Invoke-Python $q
    if ($r.Out -match 'STATE=([^;]*);OWNER=([^;]*);EVENTS=(\d+)') {
        return @{ State = $Matches[1]; Owner = $Matches[2]; Events = [int]$Matches[3] }
    }
    return @{ State = "<query failed: $($r.Out)>"; Owner = ''; Events = -1 }
}

function Get-StatusState([string]$dir) {
    $t = [System.IO.File]::ReadAllText((Join-Path $dir 'status.yaml'), $utf8)
    if ($t -match '(?m)^current_state:\s*"([^"]+)"') { return $Matches[1] }
    return ''
}

try {
    # ============================ setup ============================
    # temp registry wired through TP_SPEC_REGISTRY (inherited by all children)
    $reg = @{ projects = @(@{
        project_id = 'guardproj'; project_name = 'guardproj'
        db_path = $dbPath; root_path = $projRoot
        base_version = '5.1.0'; schema_version = 1
    }) }
    Write-Text $registryPath ($reg | ConvertTo-Json -Depth 5)
    $env:TP_SPEC_REGISTRY = $registryPath

    # ledger: schema + project + task(DEVELOPING) + db_backend_enabled=true
    $setup = @"
import sys, os
sys.path.insert(0, r'$base')
from cli import db as dbmod
db_path = r'$dbPath'
os.makedirs(os.path.dirname(db_path), exist_ok=True)
conn = dbmod.connect(db_path)
dbmod.init_schema(conn)
now = dbmod.now_iso()
with dbmod.transactional(conn):
    conn.execute("INSERT INTO project (project_id, project_name, root_path, base_version, schema_version, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                 ("guardproj", "guardproj", r'$projRoot', "5.1.0", 1, now, now))
    conn.execute("INSERT INTO task (task_id, project_id, title, risk_level, flow_level, current_state, owner_role, base_version, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 ("$taskId", "guardproj", "db guard regression", "L1", "L1", "DEVELOPING", "tp-development-engineering", "5.1.0", now, now))
    conn.execute("INSERT INTO config (key, scope, scope_id, value_json, updated_at) VALUES ('db_backend_enabled','project','guardproj','true',?)", (now,))
conn.close()
print("SETUP_OK")
"@
    $r = Invoke-Python $setup
    Check 'setup_ledger_ok' ($r.Code -eq 0 -and $r.Out -match 'SETUP_OK') $r.Out.Trim()

    # file-side task at DEVELOPING, ready for DEVELOPING -> VERIFYING
    New-TaskCopy $taskDir $taskId 'DEVELOPING' 'tp-development-engineering'
    Set-ImplReady $taskDir
    Write-Handoff $taskDir $taskId 'tp-development-engineering' 'impl done' 'VERIFYING' 'tp-verification-engineering'

    # ================= S1: DB enabled + direct flush => rejected =================
    $r = Invoke-Flush $taskDir 'tp-development-engineering'
    Check 's1_direct_flush_rejected' ($r.Code -ne 0) "rc=$($r.Code)"
    Check 's1_guidance_message' ($r.Out -match 'tp-spec\.ps1' -and $r.Out -match 'event sync') ''
    Check 's1_status_unchanged' ((Get-StatusState $taskDir) -eq 'DEVELOPING') "state=$(Get-StatusState $taskDir)"
    $ho = [System.IO.File]::ReadAllText((Join-Path $taskDir 'handoff.json'), $utf8) | ConvertFrom-Json
    Check 's1_handoff_not_consumed' (-not [bool]$ho.consumed) ''
    Check 's1_no_flush_journal' (-not (Test-Path -LiteralPath (Join-Path $taskDir '.flush-journal'))) 'guard must reject before journal/lock creation'
    $facts = Get-LedgerFacts $taskId
    Check 's1_db_state_unchanged' ($facts.State -eq 'DEVELOPING' -and $facts.Events -eq 0) "state=$($facts.State) events=$($facts.Events)"

    # ============ S2: DB enabled + tp-spec.ps1 => file/DB consistent ============
    $r = Invoke-TpSpec $taskDir 'tp-development-engineering'
    Check 's2_tpspec_rc0' ($r.Code -eq 0) "rc=$($r.Code) $($r.Out.Trim())"
    $statusText = [System.IO.File]::ReadAllText((Join-Path $taskDir 'status.yaml'), $utf8)
    Check 's2_status_verifying' ($statusText -match '(?m)^current_state:\s*"VERIFYING"') ''
    Check 's2_owner_verification' ($statusText -match '(?m)^current_owner:\s*"tp-verification-engineering"') ''
    $facts = Get-LedgerFacts $taskId
    Check 's2_db_state_verifying' ($facts.State -eq 'VERIFYING') "state=$($facts.State)"
    Check 's2_db_owner_verification' ($facts.Owner -eq 'tp-verification-engineering') "owner=$($facts.Owner)"
    Check 's2_db_events_inserted' ($facts.Events -ge 2) "events=$($facts.Events)"
    $ho = [System.IO.File]::ReadAllText((Join-Path $taskDir 'handoff.json'), $utf8) | ConvertFrom-Json
    Check 's2_handoff_consumed' ([bool]$ho.consumed -and -not [string]::IsNullOrWhiteSpace([string]$ho.flush_id)) ''

    # ============ S4: event sync retry is idempotent (same flush_id) ============
    $before = Get-LedgerFacts $taskId
    $r = Invoke-EventSync $taskId $taskDir
    Check 's4_sync_retry_rc0' ($r.Code -eq 0) "rc=$($r.Code) $($r.Out.Trim())"
    Check 's4_idempotent_output' ($r.Out -match 'idempotent') $r.Out.Trim()
    $after = Get-LedgerFacts $taskId
    Check 's4_no_duplicate_events' ($after.Events -eq $before.Events) "before=$($before.Events) after=$($after.Events)"
    Check 's4_db_state_stable' ($after.State -eq $before.State -and $after.Owner -eq $before.Owner) "state=$($after.State) owner=$($after.Owner)"

    # ====== S3: DB not enabled (task in no ledger) + direct flush => intact ======
    $taskId3 = 'TASK-20260730-802'
    $taskDir3 = Join-Path $work "proj2\.tp-spec\tasks\$taskId3"
    New-TaskCopy $taskDir3 $taskId3 'NEW' 'tp-architecture-design'
    Write-Handoff $taskDir3 $taskId3 'tp-architecture-design' 'risk L1 -> dev' 'DEVELOPING' 'tp-development-engineering'
    $r = Invoke-Flush $taskDir3 'tp-architecture-design'
    Check 's3_nondb_direct_flush_rc0' ($r.Code -eq 0) "rc=$($r.Code) $($r.Out.Trim())"
    Check 's3_status_advanced' ((Get-StatusState $taskDir3) -eq 'DEVELOPING') "state=$(Get-StatusState $taskDir3)"
    Check 's3_no_guard_message' ($r.Out -notmatch 'DB backend is enabled') ''

    # ==== S5: detection failure (no trusted verdict) + direct flush => reject ====
    # TP_SPEC_DB points at a non-SQLite file: resolve_db_path returns it, the
    # config query raises -> detection prints 'error: ...' -> guard fail-closed.
    $taskId5 = 'TASK-20260730-803'
    $taskDir5 = Join-Path $work "proj3\.tp-spec\tasks\$taskId5"
    New-TaskCopy $taskDir5 $taskId5 'DEVELOPING' 'tp-development-engineering'
    Set-ImplReady $taskDir5
    Write-Handoff $taskDir5 $taskId5 'tp-development-engineering' 'impl done' 'VERIFYING' 'tp-verification-engineering'
    $corruptDb = Join-Path $work 'corrupt.db'
    Write-Text $corruptDb "this is not a sqlite database`n"
    $env:TP_SPEC_DB = $corruptDb
    try {
        $r = Invoke-Flush $taskDir5 'tp-development-engineering'
    }
    finally {
        Remove-Item Env:TP_SPEC_DB -ErrorAction SilentlyContinue
    }
    Check 's5_detectfail_rejected' ($r.Code -ne 0) "rc=$($r.Code)"
    Check 's5_failclosed_message' ($r.Out -match 'fail-closed' -and $r.Out -match 'trusted verdict') ''
    Check 's5_no_flush_journal' (-not (Test-Path -LiteralPath (Join-Path $taskDir5 '.flush-journal'))) 'reject before journal/lock creation'
    Check 's5_status_unchanged' ((Get-StatusState $taskDir5) -eq 'DEVELOPING') "state=$(Get-StatusState $taskDir5)"
    $ho = [System.IO.File]::ReadAllText((Join-Path $taskDir5 'handoff.json'), $utf8) | ConvertFrom-Json
    Check 's5_handoff_not_consumed' (-not [bool]$ho.consumed) ''

    # == S6: DB actually enabled + wrapper detection failure => wrapper fail-closed ==
    # Task registered in the enabled guardproj ledger; TP_SPEC_DB points at the
    # corrupt file so the wrapper's own detection raises -> 'error: ...' verdict
    # -> tp-spec.ps1 must exit 9 without rebuild/flush/sync or artifact writes.
    $taskId6 = 'TASK-20260730-804'
    $taskDir6 = Join-Path $projRoot ".tp-spec\tasks\$taskId6"
    $setup6 = @"
import sys
sys.path.insert(0, r'$base')
from cli import db as dbmod
conn = dbmod.connect(r'$dbPath')
now = dbmod.now_iso()
with dbmod.transactional(conn):
    conn.execute("INSERT INTO task (task_id, project_id, title, risk_level, flow_level, current_state, owner_role, base_version, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 ("$taskId6", "guardproj", "wrapper failclosed", "L1", "L1", "DEVELOPING", "tp-development-engineering", "5.1.0", now, now))
conn.close()
print("SETUP6_OK")
"@
    $r = Invoke-Python $setup6
    Check 's6_setup_ok' ($r.Code -eq 0 -and $r.Out -match 'SETUP6_OK') $r.Out.Trim()
    New-TaskCopy $taskDir6 $taskId6 'DEVELOPING' 'tp-development-engineering'
    Set-ImplReady $taskDir6
    Write-Handoff $taskDir6 $taskId6 'tp-development-engineering' 'impl done' 'VERIFYING' 'tp-verification-engineering'
    $env:TP_SPEC_DB = $corruptDb
    try {
        $r = Invoke-TpSpec $taskDir6 'tp-development-engineering'
    }
    finally {
        Remove-Item Env:TP_SPEC_DB -ErrorAction SilentlyContinue
    }
    Check 's6_wrapper_failclosed_rc9' ($r.Code -eq 9) "rc=$($r.Code)"
    Check 's6_trusted_verdict_message' ($r.Out -match 'trusted verdict' -and $r.Out -match 'error:') ''
    Check 's6_no_rebuild_no_flush' ($r.Out -notmatch 'Projection rebuilt' -and $r.Out -notmatch 'Handoff flush committed') ''
    Check 's6_no_flush_journal' (-not (Test-Path -LiteralPath (Join-Path $taskDir6 '.flush-journal'))) 'wrapper must reject before touching the task'
    Check 's6_status_unchanged' ((Get-StatusState $taskDir6) -eq 'DEVELOPING') "state=$(Get-StatusState $taskDir6)"
    $ho = [System.IO.File]::ReadAllText((Join-Path $taskDir6 'handoff.json'), $utf8) | ConvertFrom-Json
    Check 's6_handoff_not_consumed' (-not [bool]$ho.consumed) ''
    $facts = Get-LedgerFacts $taskId6
    Check 's6_db_state_unchanged' ($facts.State -eq 'DEVELOPING' -and $facts.Events -eq 0) "state=$($facts.State) events=$($facts.Events)"
}
finally {
    Remove-Item Env:TP_SPEC_REGISTRY -ErrorAction SilentlyContinue
    Remove-Item Env:TP_SPEC_ORCHESTRATED -ErrorAction SilentlyContinue
    Remove-Item Env:TP_SPEC_DB -ErrorAction SilentlyContinue
}

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
Write-Output 'V5.1.0 DB-backend guard regression PASSED'
exit 0
