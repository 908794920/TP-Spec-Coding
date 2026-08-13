<#
.SYNOPSIS
Atomically flushes handoff.json into task facts and verifiable generated views (V5.2.0 single contract).

.DESCRIPTION
The flush follows prepare -> validate -> commit -> consume. It operates only on
artifact_contract.version=5.2.0 tasks with tool-agnostic tp-* / human_owner actors;
legacy contracts are rejected. A task-scoped lock, transaction journal, staged
files and backups make interrupted flushes recoverable. Replaying an already
consumed handoff is a successful no-op.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$TaskPath,
    [Parameter(Mandatory = $true)]
    [ValidateSet('tp-product-design', 'tp-architecture-design', 'tp-development-engineering', 'tp-verification-engineering', 'tp-delivery-convergence', 'human_owner')]
    [string]$Actor,
    [switch]$ReviewOnly,
    [Parameter(DontShow = $true)]
    [ValidateSet('none', 'write_events', 'write_status', 'generate_views', 'commit', 'consume')]
    [string]$FailureInjectionStep = 'none'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# 唯一活动契约版本：从基座 VERSION 文件动态读取（禁止硬编码）
$script:ActiveVersion = (Get-Content -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'VERSION') -Raw).Trim()
$GeneratorVersion = $script:ActiveVersion

function Get-StringHash {
    param([AllowEmptyString()][string]$Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Get-CombinedSourceHash {
    param([hashtable]$Sources)
    $manifest = @($Sources.Keys | Sort-Object | ForEach-Object {
        $normalized = ([string]$_).Replace('\', '/')
        "$normalized`n$(Get-StringHash -Text ([string]$Sources[$_]))`n"
    }) -join ''
    return Get-StringHash -Text $manifest
}

function Get-YamlScalar {
    param([string]$Text, [string]$Name)
    $match = [regex]::Match($Text, "(?m)^[ \t]*" + [regex]::Escape($Name) + "[ \t]*:[ \t]*(?<value>[^#\r\n]*)(?:[ \t]*#.*)?\r?$")
    if (-not $match.Success) { return $null }
    return $match.Groups['value'].Value.Trim().Trim('"').Trim("'")
}

function Get-YamlNestedScalar {
    param([string]$Text, [string]$Parent, [string]$Name)
    $block = [regex]::Match($Text, "(?ms)^" + [regex]::Escape($Parent) + ":[ \t]*\r?\n(?<body>(?:^[ \t]+.*(?:\r?\n|$))*)")
    if (-not $block.Success) { return $null }
    return Get-YamlScalar -Text $block.Groups['body'].Value -Name $Name
}

function Set-YamlRootBlock {
    param([string]$Text, [string]$Name, [string]$Block)
    $pattern = "(?ms)^" + [regex]::Escape($Name) + ":[ \t]*\r?\n(?:^[ \t]+.*(?:\r?\n|$))*"
    if ([regex]::IsMatch($Text, $pattern)) {
        return [regex]::Replace($Text, $pattern, $Block.TrimEnd() + "`n", 1)
    }
    return $Text.TrimEnd() + "`n" + $Block.TrimEnd() + "`n"
}

function Get-ReviewMetadata {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $frontMatter = [regex]::Match($text, '(?s)\A---\s*\r?\n(?<body>.*?)\r?\n---')
    if (-not $frontMatter.Success) { return $null }
    $body = $frontMatter.Groups['body'].Value
    return [pscustomobject]@{
        Actor    = Get-YamlNestedScalar -Text $body -Parent 'review' -Name 'actor'
        Decision = Get-YamlNestedScalar -Text $body -Parent 'review' -Name 'decision'
        Evidence = Get-YamlNestedScalar -Text $body -Parent 'review' -Name 'evidence'
        Timestamp = Get-YamlNestedScalar -Text $body -Parent 'review' -Name 'timestamp'
    }
}

function Get-ShdDeclarationForFlush {
    param([string]$Path, [bool]$IsReview)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $frontMatter = [regex]::Match($text, '(?s)\A---\s*\r?\n(?<body>.*?)\r?\n---')
    if (-not $frontMatter.Success) { return $null }
    $body = $frontMatter.Groups['body'].Value
    if ($IsReview) {
        return [pscustomobject]@{
            Decision    = Get-YamlNestedScalar -Text $body -Parent 'review' -Name 'decision'
            NextState = Get-YamlNestedScalar -Text $body -Parent 'review' -Name 'next_state'
        }
    }
    return [pscustomobject]@{
        Status      = Get-YamlNestedScalar -Text $body -Parent 'stage_handoff' -Name 'status'
        IntendedNext = Get-YamlNestedScalar -Text $body -Parent 'stage_handoff' -Name 'intended_next'
        FromState   = Get-YamlNestedScalar -Text $body -Parent 'stage_handoff' -Name 'from_state'
    }
}

function New-GeneratedView {
    param(
        [string]$Body,
        [hashtable]$Sources,
        [string]$GeneratedAt,
        [string]$FlushId
    )
    $sourceDigest = Get-CombinedSourceHash -Sources $Sources
    $contentDigest = Get-StringHash -Text $Body
    $sourceLines = @($Sources.Keys | Sort-Object | ForEach-Object { '  - "' + ([string]$_).Replace('\', '/') + '"' }) -join "`n"
    return @"
---
generated_view: true
generator_version: "$GeneratorVersion"
generated_at: "$GeneratedAt"
source_files:
$sourceLines
source_digest: "sha256:$sourceDigest"
content_digest: "sha256:$contentDigest"
flush_id: "$FlushId"
---
$Body
"@
}

function Get-GeneratedSources {
    param(
        [string]$TaskDirectory,
        [string]$TargetState,
        [string]$StatusAfter,
        [string]$EventsAfter,
        [string]$HandoffAfter
    )

    # Keep this list byte-for-byte aligned with Test-GeneratedSources.
    # Generated views must hash the post-commit forms of the three mutable
    # ledger artifacts, otherwise a successful flush is stale immediately.
    $required = @('task.md', 'acceptance.md')
    if ($TargetState -in @('VERIFYING', 'CLOSING', 'COMPLETED')) {
        $required += 'implementation.md'
    }
    if ($TargetState -in @('CLOSING', 'COMPLETED')) {
        $required += 'codex-review.md'
    }
    if ($TargetState -eq 'COMPLETED') {
        $required += 'quality-and-knowledge.md'
    }

    $sources = @{
        'status.yaml' = $StatusAfter
        'events.jsonl' = $EventsAfter
        'handoff.json' = $HandoffAfter
    }
    foreach ($relative in $required) {
        $sourcePath = Join-Path $TaskDirectory $relative
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "V5.2.0 generated view requires '$relative' before flush."
        }
        $sources[$relative] = Get-Content -LiteralPath $sourcePath -Raw -Encoding UTF8
    }
    return $sources
}

function Write-Utf8File {
    param([string]$Path, [string]$Text)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

function Save-Journal {
    param([string]$Path, [object]$Journal)
    Write-Utf8File -Path $Path -Text ($Journal | ConvertTo-Json -Depth 8)
}

function Restore-IncompleteJournal {
    param([object]$Journal)
    if ([string]$Journal.state -eq 'committed') { return }
    foreach ($target in @($Journal.targets)) {
        if ([bool]$target.existed -and (Test-Path -LiteralPath ([string]$target.backup) -PathType Leaf)) {
            Copy-Item -LiteralPath ([string]$target.backup) -Destination ([string]$target.path) -Force
        }
        elseif (-not [bool]$target.existed -and (Test-Path -LiteralPath ([string]$target.path) -PathType Leaf)) {
            Remove-Item -LiteralPath ([string]$target.path) -Force
        }
    }
}

function Commit-StagedTarget {
    param([object]$Target)
    $parent = Split-Path -Parent ([string]$Target.path)
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    if ([bool]$Target.existed) {
        $replaceBackup = [string]$Target.backup + '.replace'
        if (Test-Path -LiteralPath $replaceBackup) { Remove-Item -LiteralPath $replaceBackup -Force }
        [System.IO.File]::Replace([string]$Target.staged, [string]$Target.path, $replaceBackup)
        if (Test-Path -LiteralPath $replaceBackup) { Remove-Item -LiteralPath $replaceBackup -Force }
    }
    else {
        [System.IO.File]::Move([string]$Target.staged, [string]$Target.path)
    }
}

$task = Get-Item -LiteralPath $TaskPath -ErrorAction Stop
if (-not $task.PSIsContainer) { throw 'TaskPath must be a directory.' }
$statusPath = Join-Path $task.FullName 'status.yaml'
$handoffPath = Join-Path $task.FullName 'handoff.json'
$eventsPath = Join-Path $task.FullName 'events.jsonl'
foreach ($path in @($statusPath, $handoffPath, $eventsPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required file is missing: $path" }
}

$aiWorkRoot = $task.Parent
while ($null -ne $aiWorkRoot -and $aiWorkRoot.Name -ne '.tp-spec') { $aiWorkRoot = $aiWorkRoot.Parent }
if ($null -eq $aiWorkRoot) { throw 'TaskPath must be located below a .tp-spec directory.' }

# BUG 修复（2026-07-30）：DB 后端启用时禁止直接调用底层 flush。直调只完成
# 文件侧事务，跳过 projection rebuild 与 event sync，造成文件侧推进而 SQLite
# 账本停滞的静默割裂（TASK-21956 实证）。编排器 tp-spec.ps1 以
# TP_SPEC_ORCHESTRATED=1 豁免本守卫（单一决策点）。直调时守卫 fail-closed：
# 检测结论为 true，或无法给出可信结论（Python 缺失、库/注册表异常等）均
# 拒绝，只有明确 false 才放行，避免检测失败重新暴露账本割裂风险。
# 守卫位于 .flush-journal 创建与锁获取之前，拒绝路径真正零副作用。
if ($env:TP_SPEC_ORCHESTRATED -ne '1') {
    $guardBaseRoot = Split-Path -Parent $PSScriptRoot
    $guardDetectScript = @"
import sys, os
sys.path.insert(0, r'$guardBaseRoot')
try:
    from cli import db as dbmod
    db_path = dbmod.resolve_db_path(task_id='$($task.Name)')
    if not os.path.isfile(db_path):
        print('false')
    else:
        conn = dbmod.connect(db_path)
        try:
            row = conn.execute("SELECT value_json FROM config WHERE key='db_backend_enabled' AND scope='project'").fetchone()
            print('true' if row and row['value_json'] == 'true' else 'false')
        finally:
            conn.close()
except Exception as e:
    print('error: %s: %s' % (type(e).__name__, e))
"@
    # 与 tp-spec.ps1 一致：python -c 传多行 here-string 会因 CRLF 解析失败，
    # 改写临时 .py 文件（UTF-8 无 BOM）再执行。
    $guardDetectFile = Join-Path ([System.IO.Path]::GetTempPath()) ('tp-spec-flush-guard-' + [guid]::NewGuid().ToString('N') + '.py')
    $guardVerdict = ''
    $guardPrevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        [System.IO.File]::WriteAllText($guardDetectFile, $guardDetectScript, (New-Object System.Text.UTF8Encoding($false)))
        $guardDetectOutput = & python $guardDetectFile 2>$null
        if ($null -ne $guardDetectOutput) { $guardVerdict = ([string](@($guardDetectOutput) -join "`n")).Trim() }
    }
    catch {
        $guardVerdict = 'error: ' + $_.Exception.Message
    }
    finally {
        $ErrorActionPreference = $guardPrevEAP
        Remove-Item -LiteralPath $guardDetectFile -Force -ErrorAction SilentlyContinue
    }
    if ($guardVerdict -match '^true') {
        throw ("DB backend is enabled for task '$($task.Name)'. Calling Invoke-TpSpecHandoffFlush.ps1 directly only flushes the file side and skips 'projection rebuild' and 'event sync', leaving the SQLite ledger behind (silent drift). " +
            'Use the orchestrated entry instead: scripts/tp-spec.ps1 -TaskPath <task-path> -Actor <actor> (or tp-spec commit). ' +
            "If a drift already happened, recover with: python cli/main.py event sync --task $($task.Name) --task-dir <task-path> (idempotent, safe to retry).")
    }
    if ($guardVerdict -notmatch '^false') {
        $guardDetail = if ([string]::IsNullOrWhiteSpace($guardVerdict)) { 'no output; python missing or failed to start' } else { $guardVerdict }
        throw ("DB-backend detection did not produce a trusted verdict for task '$($task.Name)' ($guardDetail). Direct Invoke-TpSpecHandoffFlush.ps1 is rejected (fail-closed) to prevent silent file/ledger drift. " +
            'Use the orchestrated entry: scripts/tp-spec.ps1 -TaskPath <task-path> -Actor <actor>, or fix the Python/DB environment and retry.')
    }
}

$journalDirectory = Join-Path $task.FullName '.flush-journal'
New-Item -ItemType Directory -Path $journalDirectory -Force | Out-Null
$lockPath = Join-Path $journalDirectory '.active.lock'
$lockStream = $null

try {
    try {
        $lockStream = New-Object System.IO.FileStream($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    }
    catch { throw "Another flush is active for task '$($task.Name)'." }

    $statusBefore = Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8
    $artifactContractVersion = Get-YamlNestedScalar -Text $statusBefore -Parent 'artifact_contract' -Name 'version'
    # V5.2.0 单一活动契约：旧契约非终态任务须先经官方 migrate/retire；flush 不负责跨契约迁移。
    if ([string]$artifactContractVersion -ne $script:ActiveVersion) {
        throw "legacy contract task is a frozen static archive; flush only supports artifact_contract.version=$($script:ActiveVersion) (found '$artifactContractVersion')."
    }
    $GeneratorVersion = $script:ActiveVersion

    # File-mode equivalent of `tp-spec commit --review-only`: append one
    # REVIEW_COMPLETED event without changing state or consuming handoff.json.
    if ($ReviewOnly) {
        if ($Actor -ne 'tp-verification-engineering') { throw 'V5.2.0 -ReviewOnly is only available to tp-verification-engineering.' }
        $stateBefore = Get-YamlScalar -Text $statusBefore -Name 'current_state'
        if ($stateBefore -ne 'VERIFYING') { throw "V5.2.0 -ReviewOnly requires current_state=VERIFYING (got '$stateBefore')." }
        $review = Get-ReviewMetadata -Path (Join-Path $task.FullName 'codex-review.md')
        if ($null -eq $review -or $review.Actor -ne 'tp-verification-engineering' -or $review.Decision -notin @('PASS', 'FAIL', 'NEEDS_FIX') -or [string]::IsNullOrWhiteSpace($review.Evidence)) {
            throw 'V5.2.0 -ReviewOnly requires valid codex-review.md review metadata.'
        }
        $reviewTime = [DateTimeOffset]::MinValue
        if (-not [DateTimeOffset]::TryParse([string]$review.Timestamp, [ref]$reviewTime)) { throw 'V5.2.0 -ReviewOnly requires codex-review.md review.timestamp in ISO 8601 format.' }

        $existingEvents = @(Get-Content -LiteralPath $eventsPath -Encoding UTF8)
        foreach ($line in $existingEvents) {
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            $existing = $line | ConvertFrom-Json -ErrorAction Stop
            if ([string]$existing.type -eq 'REVIEW_COMPLETED' -and [string]$existing.actor -eq $Actor -and
                [string]$existing.decision -eq [string]$review.Decision -and [string]$existing.time -eq [string]$review.Timestamp -and
                @($existing.evidence) -contains [string]$review.Evidence) {
                Write-Host "Review already recorded: $($review.Decision) / $($review.Timestamp)"
                return
            }
        }
        $numbers = @($existingEvents | ForEach-Object { if ($_ -match '"id"\s*:\s*"E-(\d+)"') { [int]$Matches[1] } })
        $nextId = if ($numbers.Count -eq 0) { 1 } else { [int](($numbers | Measure-Object -Maximum).Maximum + 1) }
        $reviewEvent = [ordered]@{
            id = 'E-' + $nextId.ToString('D3'); time = [string]$review.Timestamp; type = 'REVIEW_COMPLETED'; actor = $Actor
            decision = [string]$review.Decision; evidence = @([string]$review.Evidence); handoff_id = 'review-only'; flush_id = 'review-only'
        } | ConvertTo-Json -Compress -Depth 4
        $eventsAfter = (@($existingEvents) + $reviewEvent) -join "`n"
        if (-not [string]::IsNullOrWhiteSpace($eventsAfter)) { $eventsAfter += "`n" }
        $reviewTemp = Join-Path $journalDirectory ('review-' + [guid]::NewGuid().ToString('N') + '.tmp')
        $reviewBackup = Join-Path $journalDirectory ('review-' + [guid]::NewGuid().ToString('N') + '.bak')
        try {
            Write-Utf8File -Path $reviewTemp -Text $eventsAfter
            if (-not $PSCmdlet.ShouldProcess($task.FullName, 'Record REVIEW_COMPLETED without state transition')) { return }
            [System.IO.File]::Replace($reviewTemp, $eventsPath, $reviewBackup)
            Write-Host "Review recorded: $($review.Decision) / $($review.Timestamp)"
        }
        finally {
            if (Test-Path -LiteralPath $reviewTemp -PathType Leaf) { Remove-Item -LiteralPath $reviewTemp -Force }
            if (Test-Path -LiteralPath $reviewBackup -PathType Leaf) { Remove-Item -LiteralPath $reviewBackup -Force }
        }
        return
    }

    $handoffRaw = Get-Content -LiteralPath $handoffPath -Raw -Encoding UTF8
    $handoff = $handoffRaw | ConvertFrom-Json -ErrorAction Stop
    if ([string]$handoff.schema_version -ne $script:ActiveVersion) { throw "V5.2.0 handoff.json.schema_version must be $($script:ActiveVersion)." }
    if ([string]::IsNullOrWhiteSpace([string]$handoff.summary)) { throw 'handoff.json.summary is required.' }
    if ([string]$handoff.actor -ne $Actor) { throw 'handoff.json.actor must match -Actor.' }
    if ($null -eq $handoff.next -or [string]::IsNullOrWhiteSpace([string]$handoff.next.state) -or [string]::IsNullOrWhiteSpace([string]$handoff.next.owner)) {
        throw 'handoff.json.next.state and handoff.json.next.owner are required.'
    }
    $handoffId = if ($handoff.PSObject.Properties.Name -contains 'handoff_id') { [string]$handoff.handoff_id } else { '' }
    if ([string]::IsNullOrWhiteSpace($handoffId)) {
        throw 'Versioned handoff.json.handoff_id is required.'
    }
    # V5.2.0 next_prompt 完整性与目标一致性校验。
    if ($null -eq $handoff.next_prompt) { throw 'V5.2.0 handoff.json.next_prompt is required.' }
    foreach ($field in @('target_role', 'invocation', 'task_id', 'target_state', 'risk_level', 'page_verification', 'entry', 'reading_order', 'actions', 'constraints', 'exit_expectation', 'fact_source_disclaimer')) {
        if (-not ($handoff.next_prompt.PSObject.Properties.Name -contains $field) -or $null -eq $handoff.next_prompt.$field -or
            (($field -notin @('reading_order', 'actions', 'constraints')) -and [string]::IsNullOrWhiteSpace([string]$handoff.next_prompt.$field)) -or
            (($field -in @('reading_order', 'actions', 'constraints')) -and @($handoff.next_prompt.$field).Count -eq 0)) {
            throw "V5.2.0 handoff.json.next_prompt.$field is required."
        }
    }
    if ([string]$handoff.next_prompt.target_role -ne [string]$handoff.next.owner) { throw 'V5.2.0 next_prompt.target_role must equal next.owner.' }
    if ([string]$handoff.next_prompt.target_state -ne [string]$handoff.next.state) { throw 'V5.2.0 next_prompt.target_state must equal next.state.' }
    if ([string]$handoff.next_prompt.task_id -ne $task.Name) { throw 'V5.2.0 next_prompt.task_id must equal task directory name.' }
    if ([string]$handoff.next_prompt.risk_level -ne (Get-YamlScalar -Text $statusBefore -Name 'risk_level')) { throw 'V5.2.0 next_prompt.risk_level must equal status.yaml.risk_level.' }
    if ([string]$handoff.next_prompt.entry -ne 'generated/continuation.md') { throw 'V5.2.0 next_prompt.entry must be generated/continuation.md.' }
    $stateOwners = @{ RISK_ANALYZING = 'tp-architecture-design'; REQUIREMENT_CLARIFYING = 'tp-architecture-design'; TECHNICAL_DISCOVERY = 'tp-development-engineering'; PRODUCT_DESIGNING = 'tp-product-design'; PRODUCT_CONFIRMING = 'human_owner'; TECH_DESIGNING = 'tp-architecture-design'; DISCOVERY_REVIEW_REQUIRED = 'tp-architecture-design'; CHANGE_CONFIRMING = 'human_owner'; BLOCKED = 'tp-architecture-design'; DEVELOPING = 'tp-development-engineering'; ASSISTING = 'tp-development-engineering'; VERIFYING = 'tp-verification-engineering'; BROWSER_VERIFYING = 'tp-architecture-design'; REVIEWING = 'tp-architecture-design'; CLOSING = 'tp-delivery-convergence'; CANCELLED = 'human_owner' }
    $expectedNextOwner = if ([string]$handoff.next.state -eq 'COMPLETED') {
        # V5.2.0：结项由 tp-delivery-convergence 从 CLOSING 提交。
        'tp-delivery-convergence'
    }
    elseif ($stateOwners.ContainsKey([string]$handoff.next.state)) { [string]$stateOwners[[string]$handoff.next.state] }
    else { '' }
    if (-not [string]::IsNullOrWhiteSpace($expectedNextOwner) -and [string]$handoff.next_prompt.target_role -ne $expectedNextOwner) { throw "V5.2.0 next_prompt.target_role must equal owner '$expectedNextOwner' of next state '$($handoff.next.state)'." }

    $isConsumed = ($handoff.PSObject.Properties.Name -contains 'consumed') -and [bool]$handoff.consumed
    $existingFlushId = if ($handoff.PSObject.Properties.Name -contains 'flush_id') { [string]$handoff.flush_id } else { '' }
    if ($isConsumed) {
        if ([string]::IsNullOrWhiteSpace($existingFlushId)) { throw 'Consumed handoff.json is missing flush_id.' }
        Write-Host "Handoff already committed: $handoffId / $existingFlushId"
        return
    }

    # SHD M3 转换合法性 + M2 flush 侧就绪声明校验（V5.2.0）
    $stateBefore = Get-YamlScalar -Text $statusBefore -Name 'current_state'
    $flushTransitions = @{
            NEW = @('RISK_ANALYZING','TECH_DESIGNING','DEVELOPING','CANCELLED')
            RISK_ANALYZING = @('REQUIREMENT_CLARIFYING','PRODUCT_DESIGNING','TECH_DESIGNING','DEVELOPING','TECHNICAL_DISCOVERY')
            REQUIREMENT_CLARIFYING = @('PRODUCT_DESIGNING','TECH_DESIGNING','TECHNICAL_DISCOVERY','CHANGE_CONFIRMING','BLOCKED')
            TECHNICAL_DISCOVERY = @('REQUIREMENT_CLARIFYING','TECH_DESIGNING','DISCOVERY_REVIEW_REQUIRED','BLOCKED')
            PRODUCT_DESIGNING = @('PRODUCT_CONFIRMING')
            PRODUCT_CONFIRMING = @('TECH_DESIGNING','CANCELLED')
            TECH_DESIGNING = @('DEVELOPING','CHANGE_CONFIRMING','BLOCKED')
            DISCOVERY_REVIEW_REQUIRED = @('REQUIREMENT_CLARIFYING','TECH_DESIGNING','CHANGE_CONFIRMING','DEVELOPING','BLOCKED')
            CHANGE_CONFIRMING = @('REQUIREMENT_CLARIFYING','PRODUCT_DESIGNING','TECH_DESIGNING','CANCELLED')
            BLOCKED = @('REQUIREMENT_CLARIFYING','TECHNICAL_DISCOVERY','TECH_DESIGNING','DEVELOPING','VERIFYING','CANCELLED')
            DEVELOPING = @('ASSISTING','VERIFYING','DISCOVERY_REVIEW_REQUIRED','BLOCKED')
            ASSISTING = @('VERIFYING','DISCOVERY_REVIEW_REQUIRED','BLOCKED')
            VERIFYING = @('DEVELOPING','BROWSER_VERIFYING','REVIEWING','CLOSING','DISCOVERY_REVIEW_REQUIRED','BLOCKED')
            BROWSER_VERIFYING = @('REVIEWING','CLOSING','DISCOVERY_REVIEW_REQUIRED','BLOCKED')
            REVIEWING = @('CLOSING','DEVELOPING','DISCOVERY_REVIEW_REQUIRED','BLOCKED')
            CLOSING = @('COMPLETED','BLOCKED')
    }
    # M3：handoff.next.state 必须 ∈ transitions[current_state]
    if ($flushTransitions.ContainsKey($stateBefore) -and [string]$handoff.next.state -notin $flushTransitions[$stateBefore]) {
        throw "V5.2.0 handoff.next.state '$($handoff.next.state)' is not a valid transition from '$stateBefore'."
    }
    # M2 flush 侧：从产出态前向推进时，要求就绪声明 ready/PASS 且目标状态 == handoff.next.state
    $flushShdDriver = @{
            'TECH_DESIGNING' = @{ artifact = 'task.md'; review = $false }
            'DEVELOPING'      = @{ artifact = 'implementation.md'; review = $false }
            'ASSISTING'       = @{ artifact = 'implementation.md'; review = $false }
            'VERIFYING'       = @{ artifact = 'codex-review.md'; review = $true }
    }
    $flushForwardSuccessors = @{
            'TECH_DESIGNING' = @('DEVELOPING')
            'DEVELOPING'      = @('ASSISTING','VERIFYING')
            'ASSISTING'       = @('VERIFYING')
            'VERIFYING'       = @('BROWSER_VERIFYING','REVIEWING','CLOSING')
    }
    if ($flushShdDriver.ContainsKey($stateBefore) -and $flushForwardSuccessors.ContainsKey($stateBefore) -and [string]$handoff.next.state -in $flushForwardSuccessors[$stateBefore]) {
        $shdDriver = $flushShdDriver[$stateBefore]
        $shdArtifactPath = Join-Path $task.FullName $shdDriver.artifact
        $shd = Get-ShdDeclarationForFlush -Path $shdArtifactPath -IsReview $shdDriver.review
        if ($null -eq $shd) {
            throw "V5.2.0 state '$stateBefore' requires stage_handoff declaration in '$($shdDriver.artifact)' before flush."
        }
        if ($shdDriver.review) {
            if ($shd.Decision -ne 'PASS') { throw "V5.2.0 state '$stateBefore' requires codex-review.md review.decision=PASS before flush (got '$($shd.Decision)')." }
            if ([string]::IsNullOrWhiteSpace($shd.NextState)) { throw "V5.2.0 codex-review.md review.next_state is required before flush." }
            if ([string]$shd.NextState -ne [string]$handoff.next.state) { throw "V5.2.0 codex-review.md review.next_state '$($shd.NextState)' must equal handoff.next.state '$($handoff.next.state)'." }
        }
        else {
            if ($shd.Status -ne 'ready') { throw "V5.2.0 state '$stateBefore' requires $($shdDriver.artifact) stage_handoff.status=ready before flush (got '$($shd.Status)')." }
            if ([string]::IsNullOrWhiteSpace($shd.IntendedNext)) { throw "V5.2.0 $($shdDriver.artifact) stage_handoff.intended_next is required before flush." }
            if ([string]$shd.IntendedNext -ne [string]$handoff.next.state) { throw "V5.2.0 $($shdDriver.artifact) stage_handoff.intended_next '$($shd.IntendedNext)' must equal handoff.next.state '$($handoff.next.state)'." }
        }
    }

    # V5.2.0 结单链门控（与 tp-spec commit / task transition 一致）。
    $nextState = [string]$handoff.next.state
    $nextOwner = [string]$handoff.next.owner
    if ($nextState -eq 'COMPLETED') {
        if ($stateBefore -ne 'CLOSING') { throw 'V5.2.0 completion must come from CLOSING; VERIFYING cannot reach COMPLETED directly.' }
        if ($Actor -ne 'tp-delivery-convergence' -or $nextOwner -ne 'tp-delivery-convergence') { throw 'V5.2.0 COMPLETED must be flushed by tp-delivery-convergence.' }
    }
    elseif ($nextState -eq 'CLOSING') {
        if ($Actor -ne 'tp-delivery-convergence' -or $nextOwner -ne 'tp-delivery-convergence') { throw 'V5.2.0 CLOSING may only be entered by tp-delivery-convergence.' }
        $eventsRaw = Get-Content -LiteralPath $eventsPath -Raw -Encoding UTF8
        $hasReviewPass = $false
        foreach ($ln in ($eventsRaw -split "`r?`n")) {
            if ($ln -match '"type":\s*"REVIEW_COMPLETED"' -and $ln -match '"actor":\s*"tp-verification-engineering"' -and $ln -match '"(decision|note)":\s*"PASS"') { $hasReviewPass = $true; break }
        }
        if (-not $hasReviewPass) { throw 'V5.2.0 CLOSING requires an existing tp-verification-engineering REVIEW_COMPLETED=PASS event.' }
    }

    $flushId = $existingFlushId
    $incompleteJournalPath = $null
    foreach ($candidatePath in @(Get-ChildItem -LiteralPath $journalDirectory -File -Filter '*.json' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)) {
        try {
            $candidate = Get-Content -LiteralPath $candidatePath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
            if ([string]$candidate.handoff_id -eq $handoffId -and [string]$candidate.state -ne 'committed') {
                Restore-IncompleteJournal -Journal $candidate
                $candidate.state = 'recovered'
                $candidate | Add-Member -NotePropertyName recovered_at -NotePropertyValue ((Get-Date).ToString('o')) -Force
                Save-Journal -Path $candidatePath -Journal $candidate
                $flushId = [string]$candidate.flush_id
                $incompleteJournalPath = $candidatePath
                break
            }
        }
        catch { throw "Flush journal is invalid and cannot be recovered: $candidatePath. $($_.Exception.Message)" }
    }
    if ([string]::IsNullOrWhiteSpace($flushId)) { $flushId = [guid]::NewGuid().ToString('N') }

    $transactionDirectory = Join-Path $journalDirectory $flushId
    if (Test-Path -LiteralPath $transactionDirectory) { Remove-Item -LiteralPath $transactionDirectory -Recurse -Force }
    New-Item -ItemType Directory -Path $transactionDirectory | Out-Null
    $journalPath = if ($null -ne $incompleteJournalPath) { $incompleteJournalPath } else { Join-Path $journalDirectory ($flushId + '.json') }
    $timestamp = (Get-Date).ToString('o')

    $statusAfter = [regex]::Replace($statusBefore, '(?m)^current_state:\s*.*$', "current_state: `"$($handoff.next.state)`"")
    $statusAfter = [regex]::Replace($statusAfter, '(?m)^current_owner:\s*.*$', "current_owner: `"$($handoff.next.owner)`"")
    $history = "`n  - state: `"{0}`"`n    time: `"{1}`"`n    owner: `"{2}`"`n    note: `"handoff flush by {3}; {4}`"`n" -f $handoff.next.state, $timestamp, $handoff.next.owner, $Actor, ([string]$handoff.summary).Replace('"', "'")
    $statusAfter = $statusAfter.TrimEnd() + $history

    $riskLevel = Get-YamlScalar -Text $statusBefore -Name 'risk_level'
    $flowLevel = Get-YamlScalar -Text $statusBefore -Name 'flow_level'

    $existingEvents = @(Get-Content -LiteralPath $eventsPath -Encoding UTF8)
    $numbers = @($existingEvents | ForEach-Object { if ($_ -match '"id"\s*:\s*"E-(\d+)"') { [int]$Matches[1] } })
    $nextId = if ($numbers.Count -eq 0) { 1 } else { [int](($numbers | Measure-Object -Maximum).Maximum + 1) }
    $eventObjects = @()
    if ($Actor -eq 'tp-verification-engineering' -and [string]$handoff.next.state -in @('REVIEWING', 'CLOSING', 'COMPLETED')) {
        $review = Get-ReviewMetadata -Path (Join-Path $task.FullName 'codex-review.md')
        if ($null -eq $review -or $review.Actor -ne 'tp-verification-engineering' -or $review.Decision -notin @('PASS', 'FAIL', 'NEEDS_FIX') -or [string]::IsNullOrWhiteSpace($review.Evidence)) {
            throw 'tp-verification-engineering handoff to a review-or-later state requires valid codex-review.md review metadata.'
        }
        if ($review.Decision -ne 'PASS') { throw "Review decision '$($review.Decision)' cannot enter state '$($handoff.next.state)'." }
        $reviewTime = [DateTimeOffset]::MinValue
        if (-not [DateTimeOffset]::TryParse([string]$review.Timestamp, [ref]$reviewTime)) { throw 'codex-review.md review.timestamp must be valid ISO 8601.' }
        $eventObjects += [ordered]@{
            id = 'E-' + $nextId.ToString('D3'); time = [string]$review.Timestamp; type = 'REVIEW_COMPLETED'; actor = 'tp-verification-engineering'
            decision = [string]$review.Decision; evidence = @([string]$review.Evidence); handoff_id = $handoffId; flush_id = $flushId
        }
        $nextId++
    }

    $nextPromptForEvent = if ($handoff.PSObject.Properties.Name -contains 'next_prompt') { $handoff.next_prompt } else { $null }
    $eventObjects += [ordered]@{
        id = 'E-' + $nextId.ToString('D3'); time = $timestamp; type = 'HANDOFF'; actor = $Actor
        handoff_id = $handoffId; flush_id = $flushId; note = [string]$handoff.summary
        changes = @($handoff.changes); risks = @($handoff.risks); verification = $null
        evidence = @('handoff.json'); next = [string]$handoff.next.state; next_prompt = $nextPromptForEvent
    }
    $nextId++

    $eventObjects += [ordered]@{
        id = 'E-' + $nextId.ToString('D3'); time = $timestamp; type = 'STATE'; actor = $Actor
        state = [string]$handoff.next.state; note = "handoff flush by $Actor"
        evidence = @('handoff.json'); handoff_id = $handoffId; flush_id = $flushId
    }
    $newEventLines = @($eventObjects | ForEach-Object { $_ | ConvertTo-Json -Compress -Depth 8 })
    $eventsAfter = (@($existingEvents) + $newEventLines) -join "`n"
    if (-not [string]::IsNullOrWhiteSpace($eventsAfter)) { $eventsAfter += "`n" }

    $previousEventTime = $null
    foreach ($line in ($eventsAfter -split "`r?`n")) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $preparedEvent = $line | ConvertFrom-Json -ErrorAction Stop
        $preparedEventTime = [DateTimeOffset]::MinValue
        if (-not [DateTimeOffset]::TryParse([string]$preparedEvent.time, [ref]$preparedEventTime)) { throw "Prepared event '$($preparedEvent.id)' has invalid time." }
        if ($null -ne $previousEventTime -and $preparedEventTime -lt $previousEventTime) { throw "Prepared event '$($preparedEvent.id)' is not time-monotonic." }
        $previousEventTime = $preparedEventTime
    }
    if ((Get-YamlScalar -Text $statusAfter -Name 'current_state') -ne [string]$handoff.next.state) { throw 'Prepared status state is invalid.' }

    if ($handoff.PSObject.Properties.Name -notcontains 'handoff_id') { $handoff | Add-Member -NotePropertyName handoff_id -NotePropertyValue $handoffId }
    else { $handoff.handoff_id = $handoffId }
    if ($handoff.PSObject.Properties.Name -notcontains 'flush_id') { $handoff | Add-Member -NotePropertyName flush_id -NotePropertyValue $flushId }
    else { $handoff.flush_id = $flushId }
    if ($handoff.PSObject.Properties.Name -notcontains 'consumed') { $handoff | Add-Member -NotePropertyName consumed -NotePropertyValue $true }
    else { $handoff.consumed = $true }
    if ($handoff.PSObject.Properties.Name -notcontains 'consumed_at') { $handoff | Add-Member -NotePropertyName consumed_at -NotePropertyValue $timestamp }
    else { $handoff.consumed_at = $timestamp }
    $handoffAfter = $handoff | ConvertTo-Json -Depth 10

    $changes = @($handoff.changes | ForEach-Object { "- $_" }) -join "`n"
    if ([string]::IsNullOrWhiteSpace($changes)) { $changes = '- none' }
    $risks = @($handoff.risks | ForEach-Object { "- $_" }) -join "`n"
    if ([string]::IsNullOrWhiteSpace($risks)) { $risks = '- none' }
    $nextPromptBlock = ''
    $nextSkill = if ($handoff.next.PSObject.Properties.Name -contains 'skill') { [string]$handoff.next.skill } else { 'not_applicable' }
    $readingOrder = @($handoff.next_prompt.reading_order | ForEach-Object { "- $_" }) -join "`n"
    $actions = @($handoff.next_prompt.actions | ForEach-Object { "- $_" }) -join "`n"
    $constraints = @($handoff.next_prompt.constraints | ForEach-Object { "- $_" }) -join "`n"
    $nextPromptBlock = @"

## 下一步提示词

$($handoff.next_prompt.invocation)

- 任务路径：.tp-spec/tasks/$($handoff.next_prompt.task_id)/
- 当前状态：$($handoff.next_prompt.target_state) / owner $($handoff.next_prompt.target_role) / risk $($handoff.next_prompt.risk_level) / page verification $($handoff.next_prompt.page_verification)
- 唯一入口：$($handoff.next_prompt.entry)

读取顺序：
$readingOrder

本次动作：
$actions

约束与红线：
$constraints

退出与下一步：$($handoff.next_prompt.exit_expectation)

$($handoff.next_prompt.fact_source_disclaimer)
"@
    $continuationBody = @"
# 任务接续区

> 本文件是可验证派生视图；权威事实以 status.yaml、events.jsonl 和阶段工件为准。

## 本次交接

- 执行角色：$Actor
- 结论：$($handoff.summary)

## 累计变更

$changes

## 风险与未决项

$risks

## 下一步

- 状态：$($handoff.next.state)
- 责任角色：$($handoff.next.owner)
- 目标 Skill：$nextSkill
$nextPromptBlock
"@
    $continuationSources = Get-GeneratedSources -TaskDirectory $task.FullName -TargetState ([string]$handoff.next.state) -StatusAfter $statusAfter -EventsAfter $eventsAfter -HandoffAfter $handoffAfter
    $continuation = New-GeneratedView -Body $continuationBody -Sources $continuationSources -GeneratedAt $timestamp -FlushId $flushId

    $generatedDirectory = Join-Path $task.FullName 'generated'
    $continuationPath = Join-Path $generatedDirectory 'continuation.md'
    $views = [ordered]@{ $continuationPath = $continuation }
    if ([string]$handoff.next.state -eq 'COMPLETED') {
        $finalSources = Get-GeneratedSources -TaskDirectory $task.FullName -TargetState 'COMPLETED' -StatusAfter $statusAfter -EventsAfter $eventsAfter -HandoffAfter $handoffAfter
        $finalBody = @"
# 生成的结项摘要

> 本文件是可验证派生视图；人工批准和独立审查以正式工件及事件为准。

- 任务状态：$($handoff.next.state)
- 当前责任角色：$($handoff.next.owner)
- 最近交接角色：$Actor
- 交接结论：$($handoff.summary)
- 生成时间：$timestamp
"@
        $views[(Join-Path $generatedDirectory 'final-result.md')] = New-GeneratedView -Body $finalBody -Sources $finalSources -GeneratedAt $timestamp -FlushId $flushId
    }

    $targetSpecs = @(
        [pscustomobject]@{ name = 'write_events'; path = $eventsPath; content = $eventsAfter },
        [pscustomobject]@{ name = 'write_status'; path = $statusPath; content = $statusAfter }
    )
    foreach ($view in $views.GetEnumerator()) {
        $targetSpecs += [pscustomobject]@{ name = 'generate_views'; path = [string]$view.Key; content = [string]$view.Value }
    }
    $targetSpecs += [pscustomobject]@{ name = 'consume'; path = $handoffPath; content = $handoffAfter }

    $targets = @()
    $index = 0
    foreach ($spec in $targetSpecs) {
        $index++
        $staged = Join-Path $transactionDirectory ("$index.tmp")
        $backup = Join-Path $transactionDirectory ("$index.bak")
        $existed = Test-Path -LiteralPath $spec.path -PathType Leaf
        Write-Utf8File -Path $staged -Text ([string]$spec.content)
        if ($existed) { Copy-Item -LiteralPath $spec.path -Destination $backup -Force }
        $targets += [pscustomobject]@{ name = $spec.name; path = $spec.path; staged = $staged; backup = $backup; existed = $existed; committed = $false }
    }

    $journal = [ordered]@{
        flush_id = $flushId; handoff_id = $handoffId; task_id = $task.Name; timestamp = $timestamp
        status_before = Get-StringHash -Text $statusBefore; target_state = [string]$handoff.next.state; handoff_source = $handoffPath
        steps = @('prepare', 'validate', 'write_events', 'write_status', 'generate_views', 'commit', 'consume')
        state = 'prepared'; prepared = $true; committed = $false; targets = $targets
    }
    Save-Journal -Path $journalPath -Journal $journal

    if (-not $PSCmdlet.ShouldProcess($task.FullName, "Commit handoff transaction $flushId")) {
        $journal.state = 'whatif'; Save-Journal -Path $journalPath -Journal $journal
        return
    }

    $journal.state = 'committing'; Save-Journal -Path $journalPath -Journal $journal
    try {
        foreach ($target in $targets) {
            if ($FailureInjectionStep -eq [string]$target.name) { throw "Injected failure at $($target.name)." }
            Commit-StagedTarget -Target $target
            $target.committed = $true
            Save-Journal -Path $journalPath -Journal $journal
        }
        if ($FailureInjectionStep -eq 'commit') { throw 'Injected failure at commit.' }
        $journal.state = 'committed'; $journal.committed = $true; $journal.committed_at = (Get-Date).ToString('o')
        Save-Journal -Path $journalPath -Journal $journal
    }
    catch {
        Restore-IncompleteJournal -Journal $journal
        $journal.state = 'rolled_back'; $journal.committed = $false; $journal.failure = $_.Exception.Message; $journal.rolled_back_at = (Get-Date).ToString('o')
        Save-Journal -Path $journalPath -Journal $journal
        throw
    }

    Write-Host "Handoff flush committed: $($handoff.next.state) -> $($handoff.next.owner); $handoffId / $flushId"
}
finally {
    if ($null -ne $lockStream) { $lockStream.Dispose() }
}
