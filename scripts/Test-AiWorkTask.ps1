<#
.SYNOPSIS
Read-only validation for an TP-Spec-Coding task directory.

.DESCRIPTION
V5.2.0 single-contract validator. Public Record-first tasks are checked for
identity/text safety, SQLite/state integrity, valid phase values and truthful
acceptance claims, then delegated to the Python Runtime validator. Optional
design/review/knowledge artifacts, handoff metadata and closing completeness are
not V5.2.0 progression gates. Legacy microstate checks remain below only for
historical compatibility/recovery. Never create, modify, or close task artifacts.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateNotNullOrEmpty()]
    [string]$TaskPath
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
    # New projects resolve Base from the user Installation; project-side scripts
    # Junction remains compatibility-only. Every candidate is validated by stable files.
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:AI_WORK_BASE_ROOT) { $candidates.Add($env:AI_WORK_BASE_ROOT) }
    $installed = Get-AiWorkInstallationBaseRoot
    if ($installed) { $candidates.Add($installed) }
    $candidates.Add((Split-Path -Parent $PSScriptRoot))

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

$script:BaseRoot = Resolve-AiWorkBaseRoot
if (-not $script:BaseRoot) {
    Write-Output "[Error] GOVERNANCE_LOAD_ERROR - unable to resolve TP-Spec-Coding root; configure ~/.ai-work/installation.yaml or set AI_WORK_BASE_ROOT"
    exit 1
}

# 唯一活动契约版本：从解析后的真实基座 VERSION 动态读取（禁止硬编码）
$script:ActiveVersion = (Get-Content -LiteralPath (Join-Path $script:BaseRoot 'VERSION') -Raw).Trim()

$script:Issues = @()
$TaskIdPattern = '^TASK-[A-Za-z0-9][A-Za-z0-9._-]*$'
$EventTypes = @('STATE', 'FACT', 'DECISION', 'BLOCKER', 'VERIFICATION', 'REVIEW', 'REVIEW_COMPLETED', 'HANDOFF', 'SCOPE_CHANGE', 'KNOWLEDGE')
$TerminalOrReviewStates = @('REVIEWING', 'CLOSING', 'COMPLETED')
$StrictAcceptanceStates = @('REVIEWING', 'CLOSING', 'COMPLETED')
$ActiveWorkItemStates = @('active', 'in_progress', 'developing', 'doing')
# ==================================================
# V5.2.0 P3: governance owner/transition values now come from the controlled loader (C-01.4/D-06)
# ==================================================
# The three P2 hardcoded mirror tables (StateOwners / ShdWorkflowTransitions /
# expectedOwnerByState) are deleted: the validator no longer keeps a private
# copy of governance semantics. When it needs state->owner or transitions it
# reads them once at startup from the controlled Python loader. Load failure is
# always fail-closed (never silently skip a real validation gate).
function Get-GovernanceDump {
    $mirrorBase = $script:BaseRoot
    $mainPy = Join-Path $mirrorBase 'cli\main.py'
    if (-not (Test-Path -LiteralPath $mainPy)) {
        Write-Output "[Error] GOVERNANCE_LOAD_ERROR - controlled loader not found: $mainPy"
        exit 1
    }
    $pyCmd = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not (Test-Path -LiteralPath $pyCmd)) {
        Write-Output "[Error] GOVERNANCE_LOAD_ERROR - python executable not found"
        exit 1
    }
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        $json = & $pyCmd $mainPy config dump --base-root $mirrorBase 2>$null
        $code = $LASTEXITCODE
        $ErrorActionPreference = $prevEap
        if ($code -eq 0 -and $json) {
            try { return ($json | ConvertFrom-Json) } catch { }
        }
        Start-Sleep -Milliseconds 150
    }
    Write-Output "[Error] GOVERNANCE_LOAD_ERROR - controlled dump failed after retry"
    exit 1
}

# Load governance semantics once and rebuild the former mirror tables as the
# single source of truth (read-only maps):
#   $StateOwners            <- agents/role-catalog.yaml state_owner_map
#   $ShdWorkflowTransitions <- governance/workflow.yaml transitions.*.next
$__govDump = Get-GovernanceDump
$StateOwners = @{}
foreach ($p in $__govDump.files.'role-catalog'.data.state_owner_map.PSObject.Properties) {
    $StateOwners[$p.Name] = [string]$p.Value
}
$ShdWorkflowTransitions = @{}
foreach ($p in $__govDump.files.workflow.data.transitions.PSObject.Properties) {
    $ShdWorkflowTransitions[$p.Name] = @($p.Value.next)
}


# SHD 驱动表：from_state -> @{ owner; artifact; review }（review=主工件为固定验收工件 codex-review.md）
$ShdDriverTable = @{
    'TECH_DESIGNING' = @{ owner = 'tp-architecture-design';     artifact = 'task.md';                   review = $false }
    'DEVELOPING'      = @{ owner = 'tp-development-engineering'; artifact = 'implementation.md';          review = $false }
    'ASSISTING'       = @{ owner = 'tp-development-engineering'; artifact = 'implementation.md';          review = $false }
    'VERIFYING'       = @{ owner = 'tp-verification-engineering'; artifact = 'codex-review.md';           review = $true  }
}

# SHD 前向消费者集合：from_state -> 需要 ready 声明的下游状态（不含 escape/rework）
$ShdForwardConsumers = @{
    'TECH_DESIGNING' = @('DEVELOPING','ASSISTING','VERIFYING','BROWSER_VERIFYING','REVIEWING','CLOSING','COMPLETED')
    'DEVELOPING'      = @('VERIFYING','BROWSER_VERIFYING','REVIEWING','CLOSING','COMPLETED')
    'ASSISTING'       = @('VERIFYING','BROWSER_VERIFYING','REVIEWING','CLOSING','COMPLETED')
    'VERIFYING'       = @('REVIEWING','CLOSING','COMPLETED')
}

$script:VisitedStates = @{}

function Add-Issue {
    param(
        [ValidateSet('Error', 'Warning')]
        [string]$Level,
        [string]$Code,
        [string]$Message
    )

    $script:Issues += [pscustomobject]@{
        Level   = $Level
        Code    = $Code
        Message = $Message
    }
}

function Invoke-PythonValidator {
    # Final Hardening（Task 4 §6.7）：PowerShell 与 Python 统一语义——
    # 调用 cli.validator 输出结构化 JSON 并合并 issues（fail-closed：python 不可用即报错）。
    param([string]$TaskDirectory, [string]$CurrentState)

    $mirrorBase = $script:BaseRoot
    $pyCmd = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not (Test-Path -LiteralPath $pyCmd)) {
        Add-Issue Error 'PYTHON_VALIDATOR_UNAVAILABLE' 'python interpreter unavailable; cannot run unified cli.validator (fail-closed).'
        return
    }
    $validatorModule = Join-Path $mirrorBase 'cli\validator.py'
    if (-not (Test-Path -LiteralPath $validatorModule)) {
        Add-Issue Error 'PYTHON_VALIDATOR_UNAVAILABLE' 'cli/validator.py not found; unified validator unavailable (fail-closed).'
        return
    }
    Push-Location $mirrorBase
    try {
        $validatorMode = if ($CurrentState -in @('REVIEWING', 'CLOSING', 'COMPLETED')) { 'closing' } else { 'working' }
        $jsonOut = & $pyCmd -m cli.validator --task-dir $TaskDirectory --mode $validatorMode --state $CurrentState --sections acceptance,codex-review,test-guide,scope,decisions 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($exitCode -ne 0) {
        $raw = ($jsonOut | Out-String)
        try {
            $result = $raw | ConvertFrom-Json
            foreach ($issue in @($result.issues)) {
                Add-Issue Error ([string]$issue.code) ("[cli.validator] " + [string]$issue.message)
            }
        }
        catch {
            $snippet = if ($raw.Length -gt 400) { $raw.Substring(0, 400) } else { $raw }
            Add-Issue Error 'PYTHON_VALIDATOR_ERROR' "cli.validator failed: $snippet"
        }
    }
}

function Get-YamlScalar {
    param(
        [string]$Text,
        [string]$Name
    )

    $result = [regex]::Match($Text, "(?m)^[ \t]*" + [regex]::Escape($Name) + "[ \t]*:[ \t]*(?<value>[^#\r\n]*)(?:[ \t]*#.*)?\r?$")
    if (-not $result.Success) {
        return $null
    }

    return $result.Groups['value'].Value.Trim().Trim('"').Trim("'")
}

function Get-YamlNestedScalar {
    param(
        [string]$Text,
        [string]$Parent,
        [string]$Name
    )

    $block = [regex]::Match($Text, "(?ms)^" + [regex]::Escape($Parent) + ":[ \t]*\r?\n(?<body>(?:^[ \t]+.*(?:\r?\n|$))*)")
    if (-not $block.Success) { return $null }
    return Get-YamlScalar -Text $block.Groups['body'].Value -Name $Name
}

function Get-MarkdownField {
    param(
        [string]$Text,
        [string]$Name
    )

    $result = [regex]::Match($Text, '(?m)^\s*-\s*' + [regex]::Escape($Name) + '[：:]\s*(?<value>[^\r\n]*)\r?$')
    if (-not $result.Success) { return $null }
    return $result.Groups['value'].Value.Trim()
}

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

function Get-FrontMatter {
    param([string]$Text)
    $match = [regex]::Match($Text, '(?s)\A---\s*\r?\n(?<body>.*?)\r?\n---\s*\r?\n(?<content>.*)\z')
    if (-not $match.Success) { return $null }
    return [pscustomobject]@{ Metadata = $match.Groups['body'].Value; Content = $match.Groups['content'].Value }
}

function Get-YamlList {
    param([string]$Text, [string]$Name)
    $block = [regex]::Match($Text, "(?ms)^" + [regex]::Escape($Name) + ":[ \t]*\r?\n(?<body>(?:^[ \t]+.*(?:\r?\n|$))*)")
    if (-not $block.Success) { return @() }
    return @($block.Groups['body'].Value -split "`r?`n" | ForEach-Object {
        if ($_ -match '^\s*-\s*"?(?<value>.*?)"?\s*$') { $Matches['value'] }
    } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Get-ShdDeclaration {
    param([string]$ArtifactPath, [bool]$IsReview)
    if (-not (Test-Path -LiteralPath $ArtifactPath -PathType Leaf)) { return $null }
    $text = Get-Content -LiteralPath $ArtifactPath -Raw -Encoding UTF8
    $front = Get-FrontMatter -Text $text
    if ($null -eq $front) { return $null }
    if ($IsReview) {
        $decision = Get-YamlNestedScalar -Text $front.Metadata -Parent 'review' -Name 'decision'
        $intendedNext = Get-YamlNestedScalar -Text $front.Metadata -Parent 'review' -Name 'next_state'
        return [pscustomobject]@{ Ready = ($decision -eq 'PASS'); Status = $decision; IntendedNext = $intendedNext; FromState = 'VERIFYING' }
    }
    $status = Get-YamlNestedScalar -Text $front.Metadata -Parent 'stage_handoff' -Name 'status'
    $intendedNext = Get-YamlNestedScalar -Text $front.Metadata -Parent 'stage_handoff' -Name 'intended_next'
    $fromState = Get-YamlNestedScalar -Text $front.Metadata -Parent 'stage_handoff' -Name 'from_state'
    return [pscustomobject]@{ Ready = ($status -eq 'ready'); Status = $status; IntendedNext = $intendedNext; FromState = $fromState }
}

function Test-GeneratedView {
    param(
        [string]$TaskDirectory,
        [string]$RelativePath,
        [string]$ExpectedState,
        [string]$ExpectedGeneratorVersion
    )

    $path = Join-Path $TaskDirectory $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return }
    $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    $front = Get-FrontMatter -Text $text
    if ($null -eq $front) {
        Add-Issue Error 'GENERATED_METADATA_MISSING' "Generated view '$RelativePath' has no valid front matter."
        return
    }

    if ((Get-YamlScalar -Text $front.Metadata -Name 'generated_view') -ne 'true') {
        Add-Issue Error 'GENERATED_FLAG_INVALID' "Generated view '$RelativePath' must declare generated_view: true."
    }
    $generatorVersion = Get-YamlScalar -Text $front.Metadata -Name 'generator_version'
    if ($generatorVersion -ne $ExpectedGeneratorVersion) {
        Add-Issue Error 'GENERATED_VERSION_INVALID' "Generated view '$RelativePath' uses generator_version '$generatorVersion', expected '$ExpectedGeneratorVersion'."
    }
    $generatedTimeText = Get-YamlScalar -Text $front.Metadata -Name 'generated_at'
    $generatedTime = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse($generatedTimeText, [ref]$generatedTime)) {
        Add-Issue Error 'GENERATED_TIME_INVALID' "Generated view '$RelativePath' has an invalid generated_at."
    }

    $sourceFiles = @(Get-YamlList -Text $front.Metadata -Name 'source_files')
    if ($sourceFiles.Count -eq 0) {
        Add-Issue Error 'GENERATED_SOURCES_MISSING' "Generated view '$RelativePath' has no source_files."
        return
    }
    $sources = @{}
    foreach ($sourceFile in $sourceFiles) {
        $sourcePath = Join-Path $TaskDirectory $sourceFile
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            Add-Issue Error 'GENERATED_SOURCE_MISSING' "Generated view '$RelativePath' references missing source '$sourceFile'."
            continue
        }
        $sources[$sourceFile] = Get-Content -LiteralPath $sourcePath -Raw -Encoding UTF8
        if ($generatedTime -ne [DateTimeOffset]::MinValue) {
            $sourceWriteTime = [DateTimeOffset](Get-Item -LiteralPath $sourcePath).LastWriteTimeUtc
            if ($sourceWriteTime -gt $generatedTime.ToUniversalTime().AddSeconds(2)) {
                Add-Issue Error 'GENERATED_SOURCE_NEWER' "Source '$sourceFile' is newer than generated view '$RelativePath'. Do not edit generated/*; run official 'ai-work commit --refresh' as the current owner. This is an audited Runtime write that records ARTIFACT_REFRESH in SQLite."
            }
        }
    }
    if ($sources.Count -eq $sourceFiles.Count) {
        $actualSourceDigest = 'sha256:' + (Get-CombinedSourceHash -Sources $sources)
        $declaredSourceDigest = Get-YamlScalar -Text $front.Metadata -Name 'source_digest'
        if ($declaredSourceDigest -ne $actualSourceDigest) {
            Add-Issue Error 'GENERATED_SOURCE_DIGEST_MISMATCH' "Generated view '$RelativePath' is stale or its sources changed. Do not edit generated/*; run official 'ai-work commit --refresh' as the current owner. This is an audited Runtime write that records ARTIFACT_REFRESH in SQLite."
        }
    }
    $actualContentDigest = 'sha256:' + (Get-StringHash -Text $front.Content)
    $declaredContentDigest = Get-YamlScalar -Text $front.Metadata -Name 'content_digest'
    if ($declaredContentDigest -ne $actualContentDigest) {
        Add-Issue Error 'GENERATED_CONTENT_DIGEST_MISMATCH' "Generated view '$RelativePath' was modified outside the generator. Do not repair it manually; run official 'ai-work commit --refresh' as the current owner. This is an audited Runtime write that records ARTIFACT_REFRESH in SQLite."
    }
    $continuationStateLine = "- 状态：$ExpectedState"
    $finalStateLine = "- 任务状态：$ExpectedState"
    if (-not [string]::IsNullOrWhiteSpace($ExpectedState) -and -not $front.Content.Contains($continuationStateLine) -and -not $front.Content.Contains($finalStateLine)) {
        Add-Issue Error 'GENERATED_STATE_MISMATCH' "Generated view '$RelativePath' does not represent current state '$ExpectedState'."
    }
}

function Test-GeneratedSourcesContract {
    param(
        [string]$TaskDirectory,
        [string]$RelativePath,
        [string]$CurrentState
    )
    $path = Join-Path $TaskDirectory $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return }
    $front = Get-FrontMatter -Text (Get-Content -LiteralPath $path -Raw -Encoding UTF8)
    if ($null -eq $front) { return }
    $expected = @('status.yaml', 'events.jsonl', 'handoff.json', 'task.md', 'acceptance.md')
    if ($CurrentState -in @('VERIFYING', 'CLOSING', 'COMPLETED')) {
        $expected += 'implementation.md'
    }
    if ($CurrentState -in @('CLOSING', 'COMPLETED')) {
        $expected += 'codex-review.md'
    }
    if ($CurrentState -eq 'COMPLETED') {
        $expected += 'quality-and-knowledge.md'
    }
    # V5.2.0 §3.8/§10.2：五个新工件经集中注册表纳入 source digest（存在才纳入），
    # 与生成器 commit_cmd._continuation_sources / projection_cmd.projection_source_names 对齐。
    $v511NewArtifacts = @('requirement-knowledge.md', 'requirement-clarifications.md', 'requirement-decisions.md', 'architecture-review.md', 'requirement-test-guide.md')
    foreach ($artifactName in $v511NewArtifacts) {
        if (Test-Path -LiteralPath (Join-Path $TaskDirectory $artifactName) -PathType Leaf) {
            $expected += $artifactName
        }
    }
    $actual = @(Get-YamlList -Text $front.Metadata -Name 'source_files' | Sort-Object -Unique)
    $want = @($expected | Sort-Object -Unique)
    if (($actual -join "`n") -ne ($want -join "`n")) {
        Add-Issue Error 'GENERATED_SOURCE_SET_MISMATCH' "V5.2.0 generated view '$RelativePath' must cover the formal artifacts completed before state '$CurrentState'."
    }
}

function Get-AutomatedRiskRules {
    # V5.2.0 P3/C-02: read risk-rule.yaml (automated_validation) through the controlled
    # loader instead of a runtime regex parse. pattern is a plain string field the loader
    # does not compile (D-04); YAML parsing already unescaped it. Load failure returns
    # $null so the caller fails closed with RISK_RULES_UNAVAILABLE.
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $mirrorBase = $script:BaseRoot
    $mainPy = Join-Path $mirrorBase 'cli\main.py'
    $pyCmd = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not (Test-Path -LiteralPath $mainPy) -or -not (Test-Path -LiteralPath $pyCmd)) { return $null }
    $abs = (Resolve-Path -LiteralPath $Path).Path
    $out = $null
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        $res = & $pyCmd $mainPy config load --file $abs --schema risk-rule 2>$null
        $code = $LASTEXITCODE
        $ErrorActionPreference = $prevEap
        if ($code -eq 0 -and $res) { $out = $res; break }
        Start-Sleep -Milliseconds 150
    }
    if (-not $out) { return $null }
    try { $av = ($out | ConvertFrom-Json).data.automated_validation } catch { return $null }
    if ($null -eq $av) { return $null }
    $rules = @()
    foreach ($sig in @($av.minimum_L2_signals)) {
        if ($null -ne $sig -and $sig.PSObject.Properties.Name -contains 'id') {
            $rules += [pscustomobject]@{
                Id      = ([string]$sig.id).Trim()
                Pattern = [string]$sig.pattern
            }
        }
    }
    $neg = if ($av.PSObject.Properties.Name -contains 'negative_pattern') { [string]$av.negative_pattern } else { '' }
    return [pscustomobject]@{
        Signals         = $rules
        NegativePattern = $neg
    }
}

function Get-ArtifactPath {
    param(
        [string]$Text,
        [string]$Name
    )

    $result = [regex]::Match($Text, "(?m)^[ \t]{2}" + [regex]::Escape($Name) + "[ \t]*:[ \t]*(?<value>[^#\r\n]*)(?:[ \t]*#.*)?\r?$")
    if (-not $result.Success) {
        return $null
    }

    return $result.Groups['value'].Value.Trim().Trim('"').Trim("'")
}

function Test-PathOverlap {
    param(
        [string]$Left,
        [string]$Right
    )

    $leftPath = $Left.Replace('\', '/').Trim().Trim('"').Trim("'").TrimEnd('/')
    $rightPath = $Right.Replace('\', '/').Trim().Trim('"').Trim("'").TrimEnd('/')
    if ([string]::IsNullOrWhiteSpace($leftPath) -or [string]::IsNullOrWhiteSpace($rightPath)) {
        return $false
    }

    return $leftPath -eq $rightPath -or
        $leftPath.StartsWith($rightPath + '/', [System.StringComparison]::OrdinalIgnoreCase) -or
        $rightPath.StartsWith($leftPath + '/', [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-WorkItemMetadata {
    param([System.IO.FileInfo]$File)

    $lines = Get-Content -LiteralPath $File.FullName -Encoding UTF8
    $state = $null
    $allowedPaths = @()
    $readingAllowedPaths = $false

    foreach ($line in $lines) {
        if ($line -match ('^\s*' + [char]0x72B6 + [char]0x6001 + '\s*[:\uFF1A]\s*(?<value>.+?)\s*$')) {
            $state = $Matches['value'].Trim().ToLowerInvariant()
        }

        if ($line -match ('^\s*' + [char]0x5141 + [char]0x8BB8 + [char]0x4FEE + [char]0x6539 + [char]0x8DEF + [char]0x5F84 + '\s*[:\uFF1A]\s*$')) {
            $readingAllowedPaths = $true
            continue
        }

        if ($readingAllowedPaths -and $line -match ('^\s*(' + [char]0x7981 + [char]0x6B62 + [char]0x4FEE + [char]0x6539 + [char]0x8DEF + [char]0x5F84 + '|##)')) {
            $readingAllowedPaths = $false
        }

        if ($readingAllowedPaths -and $line -match '^\s*-\s*(?<path>.+?)\s*$') {
            $candidate = $Matches['path'].Trim()
            if ($candidate -ne '-' -and -not [string]::IsNullOrWhiteSpace($candidate)) {
                $allowedPaths += $candidate
            }
        }
    }

    return [pscustomobject]@{
        Id           = [System.IO.Path]::GetFileNameWithoutExtension($File.Name)
        File         = $File.FullName
        State        = $state
        AllowedPaths = $allowedPaths
    }
}

try {
    $taskDirectory = Get-Item -LiteralPath $TaskPath -ErrorAction Stop
    if (-not $taskDirectory.PSIsContainer) {
        throw "TaskPath must be a task directory: $TaskPath"
    }
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 2
}

$taskName = $taskDirectory.Name
$statusPath = Join-Path $taskDirectory.FullName 'status.yaml'
$statusText = $null
$taskId = $null
$currentState = $null
$currentOwner = $null
$riskLevel = $null
$baseVersion = $null
$artifactContractVersion = $null

if (-not ($taskName -match $TaskIdPattern)) {
    Add-Issue Error 'TASK_DIRECTORY_FORMAT' "Task directory '$taskName' must use the TASK- prefix and then only letters, digits, dot, underscore, or hyphen."
}

if (-not (Test-Path -LiteralPath $statusPath -PathType Leaf)) {
    Add-Issue Error 'STATUS_MISSING' 'status.yaml is missing; task state cannot be validated.'
}
else {
    $statusText = Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8
    $taskId = Get-YamlScalar -Text $statusText -Name 'task_id'
    $currentState = Get-YamlScalar -Text $statusText -Name 'current_state'
    $currentOwner = Get-YamlScalar -Text $statusText -Name 'current_owner'
    $riskLevel = Get-YamlScalar -Text $statusText -Name 'risk_level'
    $baseVersion = Get-YamlScalar -Text $statusText -Name 'base_version'
    $artifactContractVersion = Get-YamlNestedScalar -Text $statusText -Parent 'artifact_contract' -Name 'version'

    if ([string]::IsNullOrWhiteSpace($taskId)) {
        Add-Issue Error 'TASK_ID_MISSING' 'status.yaml is missing task_id.'
    }
    elseif (-not ($taskId -match $TaskIdPattern)) {
        Add-Issue Error 'TASK_ID_FORMAT' "status.yaml.task_id '$taskId' must use the TASK- prefix and then only letters, digits, dot, underscore, or hyphen."
    }
    elseif ($taskId -ne $taskName) {
        Add-Issue Error 'TASK_ID_MISMATCH' "Task directory '$taskName' does not match status.yaml.task_id '$taskId'."
    }

    if ([string]::IsNullOrWhiteSpace($currentState)) {
        Add-Issue Error 'CURRENT_STATE_MISSING' 'status.yaml is missing current_state.'
    }

    if ([string]::IsNullOrWhiteSpace($currentOwner)) {
        Add-Issue Warning 'CURRENT_OWNER_MISSING' 'status.yaml is missing current_owner.'
    }
}

# V5.2.0 单一活动契约：旧契约非终态任务须先经官方 migrate/retire；本验证入口不代替跨契约迁移。
if (-not [string]::IsNullOrWhiteSpace($statusText) -and [string]$artifactContractVersion -ne $script:ActiveVersion) {
    Write-Output 'TP-Spec-Coding task validation summary (V5.2.0 single active contract)'
    Write-Output "Task directory: $($taskDirectory.FullName)"
    Write-Output "Task id: $taskId"
    Write-Output "Current state: $currentState"
    Write-Output "Current owner: $currentOwner"
    Write-Output "Risk level: $riskLevel"
    Write-Output "Work item count: 0"
    Write-Output 'Errors: 1; warnings: 0'
    Write-Output "[Error] LEGACY_CONTRACT_REJECTED - artifact_contract.version '$artifactContractVersion' is a frozen legacy contract; the V5.2.0 runtime validates only $($script:ActiveVersion). Historical tasks are static audit archives kept in Git release branches."
    exit 1
}

# V5.2.0 Record-first fast path. The PowerShell wrapper validates identity/text basics
# above, then delegates ledger truth to the Runtime. Legacy SHD/closing/artifact gates
# below remain only for compatibility code reading and are not part of the active path.
if (-not [string]::IsNullOrWhiteSpace($statusText) -and [string]$artifactContractVersion -eq $script:ActiveVersion -and
    $currentState -in @('NEW','ACTIVE','BLOCKED','COMPLETED','CANCELLED')) {
    foreach ($f in Get-ChildItem -LiteralPath $taskDirectory.FullName -File -Recurse -ErrorAction SilentlyContinue) {
        if ($f.Extension -notin @('.md','.yaml','.yml','.json','.jsonl','.txt')) { continue }
        try {
            $raw = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8
            if ($raw.Contains([char]0)) { Add-Issue Error 'TEXT_NUL' "Text artifact contains NUL: $($f.FullName)" }
        } catch { Add-Issue Error 'TEXT_READ_ERROR' "Cannot read text artifact as UTF-8: $($f.FullName)" }
    }
    if (($script:Issues | Where-Object { $_.Level -eq 'Error' }).Count -eq 0) {
        $mainPy = Join-Path $script:BaseRoot 'cli\main.py'
        $pyCmd = (Get-Command python -ErrorAction SilentlyContinue).Source
        if (-not (Test-Path -LiteralPath $pyCmd)) {
            Add-Issue Error 'RUNTIME_VALIDATOR_UNAVAILABLE' 'python interpreter unavailable; cannot validate Runtime ledger.'
        } else {
            $projectRoot = $taskDirectory.Parent.FullName
            $cursor = $taskDirectory
            while ($cursor -and $cursor.Name -ne '.ai-work') { $cursor = $cursor.Parent }
            if ($cursor -and $cursor.Parent) { $projectRoot = $cursor.Parent.FullName }
            Push-Location $projectRoot
            try {
                $out = & $pyCmd $mainPy task validate --task $taskId --task-dir $taskDirectory.FullName 2>&1
                $code = $LASTEXITCODE
            } finally { Pop-Location }
            if ($code -ne 0) { Add-Issue Error 'RUNTIME_INTEGRITY_FAILED' (($out | Out-String).Trim()) }
        }
    }
    $errors = @($script:Issues | Where-Object { $_.Level -eq 'Error' })
    $warnings = @($script:Issues | Where-Object { $_.Level -eq 'Warning' })
    Write-Output 'TP-Spec-Coding task validation summary (V5.2.0 Record-first integrity)'
    Write-Output "Task directory: $($taskDirectory.FullName)"
    Write-Output "Task id: $taskId"
    Write-Output "Current state: $currentState"
    Write-Output "Current owner: $currentOwner"
    Write-Output "Risk level: $riskLevel"
    Write-Output "Errors: $($errors.Count); warnings: $($warnings.Count)"
    foreach ($issue in $script:Issues) { Write-Output "[$($issue.Level)] $($issue.Code) - $($issue.Message)" }
    if ($errors.Count -gt 0) { exit 1 }
    exit 0
}

$artifactDefaults = [ordered]@{
    event_log    = 'events.jsonl'
    continuation = 'continuation.md'
    handoff      = 'handoff.json'
    acceptance   = 'acceptance.md'
    work_items   = 'work-items'
}

# V5.2.0 单一活动契约：入口已拒绝旧契约，以下门控均按 5.2.0 语义恒定。
$requiresCoreArtifacts = $true
$requiresCanonicalRoleGate = $true
$requiresArtifactContract = $true
$requiresHandoffClosure = $true
$requiresClosingChain = $true
$requiresHandoffGate = ($riskLevel -in @('L2', 'L3')) -and
    ($currentState -in @('DEVELOPING', 'VERIFYING', 'REVIEWING'))

$artifactPaths = @{}
foreach ($artifact in @($artifactDefaults.Keys)) {
    $relativePath = $artifactDefaults[$artifact]
    $isDeclared = $false
    if ($null -ne $statusText) {
        $declaredPath = Get-ArtifactPath -Text $statusText -Name $artifact
        if (-not [string]::IsNullOrWhiteSpace($declaredPath)) {
            $relativePath = $declaredPath
            $isDeclared = $true
        }
    }

    $artifactPaths[$artifact] = $relativePath
    $artifactPath = Join-Path $taskDirectory.FullName $relativePath
    $requiredByBaseline = $requiresCoreArtifacts -and $artifact -ne 'handoff' -and
        (-not $requiresArtifactContract -or $artifact -in @('event_log', 'acceptance'))
    $declaredArtifactRequired = $isDeclared -and -not (
        $requiresArtifactContract -and $artifact -in @('continuation', 'handoff', 'work_items')
    )
    if (($declaredArtifactRequired -or $requiredByBaseline) -and -not (Test-Path -LiteralPath $artifactPath)) {
        Add-Issue Error 'DECLARED_ARTIFACT_MISSING' "Required V3 P0 artifact '$relativePath' is missing ($artifact)."
    }
}

if ($requiresArtifactContract) {
    $requiredArtifacts = [ordered]@{
        task_document        = 'task.md'
        acceptance           = 'acceptance.md'
        implementation       = 'implementation.md'
        review_artifact     = 'codex-review.md'
        quality_and_knowledge = 'quality-and-knowledge.md'
        continuation         = 'generated/continuation.md'
        final_result         = 'generated/final-result.md'
    }

    foreach ($artifact in $requiredArtifacts.GetEnumerator()) {
        $artifactPath = Join-Path $taskDirectory.FullName $artifact.Value
        $isRequired = switch ($artifact.Key) {
            'task_document' { $true }
            'acceptance' { $true }
            'implementation' { $currentState -in @('VERIFYING', 'BROWSER_VERIFYING', 'REVIEWING', 'CLOSING', 'COMPLETED') }
            'review_artifact' { $currentState -in @('REVIEWING', 'CLOSING', 'COMPLETED') }
            'quality_and_knowledge' { $currentState -in @('CLOSING', 'COMPLETED') }
            'continuation' { $currentState -in @('DEVELOPING', 'VERIFYING', 'BROWSER_VERIFYING', 'REVIEWING') }
            'final_result' { $currentState -eq 'COMPLETED' }
        }
        if ($isRequired -and -not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
            Add-Issue Error 'ARTIFACT_MISSING' "task artifact '$($artifact.Value)' is required for state '$currentState'."
        }
    }

    $taskDocumentPath = Join-Path $taskDirectory.FullName 'task.md'
    if (Test-Path -LiteralPath $taskDocumentPath -PathType Leaf) {
        $taskDocument = Get-Content -LiteralPath $taskDocumentPath -Raw -Encoding UTF8
        $knowledgeMarker = '<!-- knowledge-retrieval -->'
        $knowledgeGateStates = @('TECH_DESIGNING', 'DEVELOPING', 'VERIFYING', 'BROWSER_VERIFYING', 'REVIEWING', 'COMPLETED')
        $knowledgeGateRequired = ($riskLevel -in @('L2', 'L3')) -and ($currentState -in $knowledgeGateStates)

        if (-not $taskDocument.Contains($knowledgeMarker)) {
            if ($knowledgeGateRequired) {
                Add-Issue Warning 'KNOWLEDGE_RETRIEVAL_RECORD_MISSING' 'L2/L3 task has no knowledge-retrieval record. Backfill through tp-architecture-design when the task is next reviewed; this warning does not block an in-flight task.'
            }
        }
        elseif ($knowledgeGateRequired) {
            $statusTextValue = [string](Get-MarkdownField -Text $taskDocument -Name '检索状态')
            $statusMatch = [regex]::Match($statusTextValue, '(?i)\b(HIT|NO_HIT|NOT_APPLICABLE|PENDING)\b')
            $knowledgeStatus = if ($statusMatch.Success) { $statusMatch.Groups[1].Value.ToUpperInvariant() } else { '' }
            $knowledgeTarget = [string](Get-MarkdownField -Text $taskDocument -Name '知识目标')
            $knowledgeQuery = [string](Get-MarkdownField -Text $taskDocument -Name '查询词')
            $knowledgeHits = [string](Get-MarkdownField -Text $taskDocument -Name '命中知识')
            $knowledgeDecision = [string](Get-MarkdownField -Text $taskDocument -Name '采用、冲突与影响判断')
            $knowledgeNotApplicable = [string](Get-MarkdownField -Text $taskDocument -Name '不适用理由')

            if ($knowledgeStatus -eq '' -or $knowledgeStatus -eq 'PENDING') {
                Add-Issue Error 'KNOWLEDGE_RETRIEVAL_INCOMPLETE' "L2/L3 state '$currentState' requires knowledge status HIT, NO_HIT, or NOT_APPLICABLE."
            }
            elseif ($knowledgeStatus -eq 'HIT') {
                if ([string]::IsNullOrWhiteSpace($knowledgeTarget) -or [string]::IsNullOrWhiteSpace($knowledgeQuery) -or
                    [string]::IsNullOrWhiteSpace($knowledgeHits) -or [string]::IsNullOrWhiteSpace($knowledgeDecision)) {
                    Add-Issue Error 'KNOWLEDGE_RETRIEVAL_EVIDENCE_MISSING' 'Knowledge status HIT requires target, query, hit paths, and adoption/conflict/impact judgment.'
                }
            }
            elseif ($knowledgeStatus -eq 'NO_HIT') {
                if ([string]::IsNullOrWhiteSpace($knowledgeTarget) -or [string]::IsNullOrWhiteSpace($knowledgeQuery) -or [string]::IsNullOrWhiteSpace($knowledgeDecision)) {
                    Add-Issue Error 'KNOWLEDGE_RETRIEVAL_EVIDENCE_MISSING' 'Knowledge status NO_HIT requires target, query, and the code/discovery evidence used instead.'
                }
            }
            elseif ($knowledgeStatus -eq 'NOT_APPLICABLE' -and [string]::IsNullOrWhiteSpace($knowledgeNotApplicable)) {
                Add-Issue Error 'KNOWLEDGE_RETRIEVAL_REASON_MISSING' 'Knowledge status NOT_APPLICABLE requires a non-empty reason limited to non-business governance, formatting, or task-ledger work.'
            }
        }
    }
}

# ==================================================
# V5.2.0 Hardening（审查报告 P0-2/P0-3/P1-3/P1-5）：
# 五新工件 / L2/L3 架构评审 PASS 与 stale / 验收结单门禁 / test guide lifecycle
# 与 Python cli/transition_service.validate_transition 语义对齐（fail-closed）。
# ==================================================
if ($requiresArtifactContract) {
    $hardenNewArtifacts = @(
        'requirement-knowledge.md',
        'requirement-clarifications.md',
        'requirement-decisions.md',
        'architecture-review.md',
        'requirement-test-guide.md'
    )
    # L2/L3 任务在 DEVELOPING 及之后必须存在全部五新工件（无则 HARDEN_ARTIFACT_MISSING）。
    $hardenL23 = ($riskLevel -in @('L2', 'L3')) -or
        ([string](Get-YamlScalar -Text $statusText -Name 'flow_level') -in @('L2', 'L3'))
    if ($hardenL23 -and $currentState -in @('DEVELOPING', 'VERIFYING', 'BROWSER_VERIFYING', 'REVIEWING', 'CLOSING', 'COMPLETED')) {
        foreach ($name in $hardenNewArtifacts) {
            $p = Join-Path $taskDirectory.FullName $name
            if (-not (Test-Path -LiteralPath $p -PathType Leaf)) {
                Add-Issue Error 'HARDEN_ARTIFACT_MISSING' "V5.2.0 L2/L3 requires new artifact '$name' for state '$currentState'."
            }
        }
    }

    # 架构评审（tp-architecture-review）：L2/L3 进入 DEVELOPING 后必须存在 ARCHITECTURE PASS。
    if ($hardenL23 -and $currentState -in @('DEVELOPING', 'VERIFYING', 'BROWSER_VERIFYING', 'REVIEWING', 'CLOSING', 'COMPLETED')) {
        $archEvent = $null
        $archReviewPath = Join-Path $taskDirectory.FullName 'architecture-review.md'
        if (Test-Path -LiteralPath $archReviewPath -PathType Leaf) {
            $archText = Get-Content -LiteralPath $archReviewPath -Raw -Encoding UTF8
            $archFront = Get-FrontMatter -Text $archText
            if ($null -ne $archFront) {
                $archDecision = Get-YamlNestedScalar -Text $archFront.Metadata -Parent 'review' -Name 'decision'
                if ($archDecision -ne 'PASS') {
                    Add-Issue Error 'HARDEN_ARCH_REVIEW_REQUIRED' "V5.2.0 L2/L3 architecture-review.md review.decision must be PASS, got '$archDecision'."
                }
            }
            else {
                Add-Issue Error 'HARDEN_ARCH_REVIEW_REQUIRED' 'V5.2.0 L2/L3 architecture-review.md is missing structured review front matter.'
            }
        }
        $archEventFound = $false
        $eventLogPath = Join-Path $taskDirectory.FullName $artifactDefaults['event_log']
        if (Test-Path -LiteralPath $eventLogPath -PathType Leaf) {
            foreach ($rawLine in (Get-Content -LiteralPath $eventLogPath -Encoding UTF8)) {
                if ([string]::IsNullOrWhiteSpace($rawLine)) { continue }
                try {
                    $evt = $rawLine | ConvertFrom-Json -ErrorAction Stop
                }
                catch { continue }
                if ([string]$evt.type -eq 'REVIEW_COMPLETED' -and [string]$evt.actor -eq 'tp-architecture-review' -and [string]$evt.decision -eq 'PASS') {
                    $archEventFound = $true
                    break
                }
            }
        }
        if (-not $archEventFound) {
            Add-Issue Error 'HARDEN_ARCH_REVIEW_REQUIRED' "V5.2.0 L2/L3 requires a tp-architecture-review REVIEW_COMPLETED PASS event for state '$currentState'."
        }
    }

    # 结单门禁：acceptance 存在时做 fail-closed YAML/表格结构校验 + scope change + test guide lifecycle。
    if ($currentState -in @('REVIEWING', 'CLOSING', 'COMPLETED')) {
        # test guide lifecycle 的 verification_results 必须 done
        $tgPath = Join-Path $taskDirectory.FullName 'requirement-test-guide.md'
        if (Test-Path -LiteralPath $tgPath -PathType Leaf) {
            $tgText = Get-Content -LiteralPath $tgPath -Raw -Encoding UTF8
            $tgFront = Get-FrontMatter -Text $tgText
            if ($null -ne $tgFront) {
                $tgVerification = Get-YamlNestedScalar -Text $tgFront.Metadata -Parent 'lifecycle' -Name 'verification_results'
                if ($tgVerification -notin @('done', 'completed', 'complete')) {
                    Add-Issue Error 'HARDEN_TEST_GUIDE_INCOMPLETE' "V5.2.0 closing state '$currentState' requires requirement-test-guide.md lifecycle.verification_results done."
                }
            }
        }
        # codex-review 正文必须含结论/证据/残余风险（P0-3：空正文拒绝）
        $crPath = Join-Path $taskDirectory.FullName 'codex-review.md'
        if (Test-Path -LiteralPath $crPath -PathType Leaf) {
            $crText = Get-Content -LiteralPath $crPath -Raw -Encoding UTF8
            $crFront = Get-FrontMatter -Text $crText
            $crBody = if ($null -ne $crFront) { $crFront.Content } else { $crText }
            if ($crBody -notmatch '结论' -or $crBody -notmatch '证据' -or $crBody -notmatch '残余风险') {
                Add-Issue Error 'HARDEN_CODE_REVIEW_EMPTY' 'V5.2.0 closing requires codex-review.md body containing 结论/证据/残余风险 sections.'
            }
        }
    }
}

if ($requiresCanonicalRoleGate) {
    # owner values come from the loader-backed $StateOwners (role-catalog.state_owner_map),
    # no longer hardcoded; limited to the 5 dev/verify/closing states this gate covers.
    $expectedOwnerByState = @{}
    foreach ($s in @('TECHNICAL_DISCOVERY','DEVELOPING','ASSISTING','VERIFYING','CLOSING')) {
        if ($StateOwners.ContainsKey($s)) { $expectedOwnerByState[$s] = $StateOwners[$s] }
    }
    if ($expectedOwnerByState.ContainsKey($currentState) -and $currentOwner -ne $expectedOwnerByState[$currentState]) {
        Add-Issue Error 'CANONICAL_OWNER_MISMATCH' "state '$currentState' must be owned by '$($expectedOwnerByState[$currentState])', not '$currentOwner'."
    }
}

if ($requiresHandoffGate) {
    $continuationRelativePath = 'generated/continuation.md'
    $continuationPath = Join-Path $taskDirectory.FullName $continuationRelativePath
    if (-not (Test-Path -LiteralPath $continuationPath -PathType Leaf)) {
        Add-Issue Error 'HANDOFF_MISSING' "V4.1 handoff requires '$continuationRelativePath'."
    }
}

$workItemsDirectory = Join-Path $taskDirectory.FullName $artifactPaths['work_items']
$workItems = @()
if (Test-Path -LiteralPath $workItemsDirectory -PathType Container) {
    $workItems = @(Get-ChildItem -LiteralPath $workItemsDirectory -File -Filter '*.md' | ForEach-Object { Get-WorkItemMetadata -File $_ })
}

$workItemIds = @{}
foreach ($workItem in $workItems) {
    $workItemIds[$workItem.Id] = $true
    if ($ActiveWorkItemStates -contains $workItem.State -and $workItem.AllowedPaths.Count -eq 0) {
        Add-Issue Warning 'ACTIVE_WORK_ITEM_PATHS_MISSING' "Active work item '$($workItem.Id)' has no allowed paths."
    }
}

for ($leftIndex = 0; $leftIndex -lt $workItems.Count; $leftIndex++) {
    $left = $workItems[$leftIndex]
    if (-not ($ActiveWorkItemStates -contains $left.State)) {
        continue
    }

    for ($rightIndex = $leftIndex + 1; $rightIndex -lt $workItems.Count; $rightIndex++) {
        $right = $workItems[$rightIndex]
        if (-not ($ActiveWorkItemStates -contains $right.State)) {
            continue
        }

        foreach ($leftPath in $left.AllowedPaths) {
            foreach ($rightPath in $right.AllowedPaths) {
                if (Test-PathOverlap -Left $leftPath -Right $rightPath) {
                    Add-Issue Error 'WORK_ITEM_PATH_OVERLAP' "Active work items '$($left.Id)' and '$($right.Id)' overlap: '$leftPath' / '$rightPath'."
                }
            }
        }
    }
}

$eventPath = Join-Path $taskDirectory.FullName $artifactPaths['event_log']
$latestStateEvent = $null
$latestReviewEvent = $null
$riskEventLines = @()
if (Test-Path -LiteralPath $eventPath -PathType Leaf) {
    $previousTime = $null
    $lineNumber = 0
    foreach ($line in (Get-Content -LiteralPath $eventPath -Encoding UTF8)) {
        $lineNumber++
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        try {
            $event = $line | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            Add-Issue Error 'EVENT_JSON_INVALID' "events.jsonl line $lineNumber is not valid JSON: $($_.Exception.Message)"
            continue
        }

        foreach ($field in @('id', 'time', 'type', 'actor')) {
            if (-not ($event.PSObject.Properties.Name -contains $field) -or [string]::IsNullOrWhiteSpace([string]$event.$field)) {
                Add-Issue Error 'EVENT_FIELD_MISSING' "events.jsonl line $lineNumber is missing required field '$field'."
            }
        }

        if ($event.PSObject.Properties.Name -contains 'type' -and $EventTypes -notcontains [string]$event.type) {
            Add-Issue Error 'EVENT_TYPE_INVALID' "events.jsonl line $lineNumber has unsupported type '$($event.type)'."
        }

        $eventTime = [DateTimeOffset]::MinValue
        if ($event.PSObject.Properties.Name -contains 'time' -and -not [DateTimeOffset]::TryParse([string]$event.time, [ref]$eventTime)) {
            Add-Issue Error 'EVENT_TIME_INVALID' "events.jsonl line $lineNumber has an invalid ISO 8601 time with offset: '$($event.time)'."
        }
        elseif ($eventTime -ne [DateTimeOffset]::MinValue) {
            if ($null -ne $previousTime -and $eventTime -lt $previousTime) {
                Add-Issue Error 'EVENT_TIME_NOT_MONOTONIC' "events.jsonl line $lineNumber is earlier than the preceding event."
            }
            $previousTime = $eventTime
        }

        if ([string]$event.type -eq 'STATE') {
            if (-not ($event.PSObject.Properties.Name -contains 'state') -or [string]::IsNullOrWhiteSpace([string]$event.state)) {
                Add-Issue Error 'STATE_EVENT_STATE_MISSING' "STATE event on events.jsonl line $lineNumber is missing state."
            }
            else {
                $latestStateEvent = $event
                $script:VisitedStates[[string]$event.state] = $true
            }
        }

        if ([string]$event.type -eq 'REVIEW_COMPLETED' -and [string]$event.actor -eq 'tp-verification-engineering') {
            $latestReviewEvent = $event
        }

        if ([string]$event.type -eq 'SCOPE_CHANGE') {
            $riskEventLines += [string]$event.note
        }
    }
}

if ($null -ne $latestStateEvent -and -not [string]::IsNullOrWhiteSpace($currentState)) {
    if ([string]$latestStateEvent.state -ne $currentState) {
        Add-Issue Error 'STATE_EVENT_MISMATCH' "status.yaml.current_state '$currentState' differs from latest STATE event '$($latestStateEvent.state)'."
    }
}
elseif ($null -ne $statusText -and (Test-Path -LiteralPath $eventPath -PathType Leaf)) {
    Add-Issue Warning 'STATE_EVENT_MISSING' 'events.jsonl has no STATE event to compare with status.yaml.'
}

if ($requiresHandoffClosure -and -not [string]::IsNullOrWhiteSpace($currentState)) {
    # M1 反向一致性：current_state 是产出态时，就绪声明 ready/PASS 但状态未推进 → HANDOFF_PENDING
    if ($ShdDriverTable.ContainsKey($currentState)) {
        $driver = $ShdDriverTable[$currentState]
        $artifactPath = Join-Path $taskDirectory.FullName $driver.artifact
        $decl = Get-ShdDeclaration -ArtifactPath $artifactPath -IsReview $driver.review
        if ($null -ne $decl -and [string]::IsNullOrWhiteSpace($decl.FromState) -eq $false -and $decl.FromState -eq $currentState) {
            if ($decl.Ready) {
                Add-Issue Error 'HANDOFF_PENDING' "stage $currentState 已声明就绪但状态未推进，请执行 flush / task transition。"
                # HPB: 交接提示词绑定——ready 窗口内校验 next_prompt 完整性与目标一致性
                $handoffPath = Join-Path $taskDirectory.FullName 'handoff.json'
                $handoffObj = $null
                try { $handoffObj = Get-Content -LiteralPath $handoffPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop } catch { }
                $np = $null
                if ($null -ne $handoffObj -and $handoffObj.PSObject.Properties.Name -contains 'next_prompt') { $np = $handoffObj.next_prompt }
                $hpbRequiredFields = @('target_role','target_state','invocation','task_id','risk_level','page_verification','entry','reading_order','actions','constraints','exit_expectation','fact_source_disclaimer')
                if ($null -eq $np) {
                    Add-Issue Error 'HANDOFF_PROMPT_MISSING' "stage $currentState 已声明就绪，但缺少面向下一角色的可复制接续提示词，交接前必须补齐。"
                }
                else {
                    $missingFields = @()
                    foreach ($f in $hpbRequiredFields) {
                        $fVal = if ($np.PSObject.Properties.Name -contains $f) { [string]$np.$f } else { '' }
                        if ([string]::IsNullOrWhiteSpace($fVal)) { $missingFields += $f }
                    }
                    if ($missingFields.Count -gt 0) {
                        Add-Issue Error 'HANDOFF_PROMPT_MISSING' "stage $currentState 已声明就绪，但 next_prompt 缺少字段：$($missingFields -join ', ')。"
                    }
                    else {
                        if ([string]$np.target_state -ne [string]$decl.IntendedNext) {
                            Add-Issue Error 'HANDOFF_PROMPT_TARGET_MISMATCH' "next_prompt.target_state '$($np.target_state)' 必须等于 intended_next '$($decl.IntendedNext)'。"
                        }
                        $hpbExpectedRole = if ([string]$decl.IntendedNext -eq 'COMPLETED') {
                            # V5.2.0：结项由 tp-delivery-convergence 从 CLOSING 提交。
                            'tp-delivery-convergence'
                        }
                        elseif ($StateOwners.ContainsKey([string]$decl.IntendedNext)) { [string]$StateOwners[[string]$decl.IntendedNext] }
                        else { '' }
                        if (-not [string]::IsNullOrWhiteSpace($hpbExpectedRole) -and [string]$np.target_role -ne $hpbExpectedRole) {
                            Add-Issue Error 'HANDOFF_PROMPT_TARGET_MISMATCH' "next_prompt.target_role '$($np.target_role)' 必须是目标态 '$($decl.IntendedNext)' 的规范 owner '$hpbExpectedRole'。"
                        }
                    }
                }
            }
            if (-not [string]::IsNullOrWhiteSpace($decl.IntendedNext) -and $ShdWorkflowTransitions.ContainsKey($currentState) -and $decl.IntendedNext -notin $ShdWorkflowTransitions[$currentState]) {
                Add-Issue Error 'HANDOFF_NEXT_ILLEGAL' "stage $currentState 的 intended_next '$($decl.IntendedNext)' 不是合法后继。"
            }
        }
    }

    # M2 前向完整性：current_state 已推进到需要下游工件之后，上游产出工件必须 ready/PASS
    foreach ($fromState in $ShdDriverTable.Keys) {
        if (-not $script:VisitedStates.ContainsKey($fromState)) { continue }
        $consumers = $ShdForwardConsumers[$fromState]
        if ($currentState -notin $consumers) { continue }
        $driver = $ShdDriverTable[$fromState]
        $artifactPath = Join-Path $taskDirectory.FullName $driver.artifact
        $decl = Get-ShdDeclaration -ArtifactPath $artifactPath -IsReview $driver.review
        # 仅当 SHD 的 from_state 匹配当前检查的上游产出态时才校验（避免同一工件的多个产出态重复报错）
        if ($null -eq $decl -or [string]::IsNullOrWhiteSpace($decl.FromState) -or $decl.FromState -ne $fromState) { continue }
        if (-not $decl.Ready) {
            Add-Issue Error 'HANDOFF_DECL_MISSING' "状态 '$currentState' 需要 '$($driver.artifact)' 的就绪声明（from_state=$fromState），但 status 仍为 draft/未声明 ready。"
        }
        elseif (-not [string]::IsNullOrWhiteSpace($decl.IntendedNext) -and $ShdWorkflowTransitions.ContainsKey($fromState) -and $decl.IntendedNext -notin $ShdWorkflowTransitions[$fromState]) {
            Add-Issue Error 'HANDOFF_NEXT_ILLEGAL' "stage $fromState 的 intended_next '$($decl.IntendedNext)' 不是合法后继。"
        }
    }
}

if ($requiresArtifactContract) {
    $generatedRelativePath = if ($currentState -eq 'COMPLETED') { 'generated/final-result.md' } else { 'generated/continuation.md' }
    if (Test-Path -LiteralPath (Join-Path $taskDirectory.FullName $generatedRelativePath) -PathType Leaf) {
        Test-GeneratedView -TaskDirectory $taskDirectory.FullName -RelativePath $generatedRelativePath -ExpectedState $currentState -ExpectedGeneratorVersion $artifactContractVersion
        if ($requiresClosingChain) {
            Test-GeneratedSourcesContract -TaskDirectory $taskDirectory.FullName -RelativePath $generatedRelativePath -CurrentState $currentState
        }
    }

    if ($requiresClosingChain) {
        $generatedDirectory = Join-Path $taskDirectory.FullName 'generated'
        if (Test-Path -LiteralPath $generatedDirectory -PathType Container) {
            $allowedGenerated = @('continuation.md', 'final-result.md')
            Get-ChildItem -LiteralPath $generatedDirectory -Force -Recurse | ForEach-Object {
                $relative = $_.FullName.Substring($generatedDirectory.Length).TrimStart('\', '/')
                if ($_.PSIsContainer -or $relative -notin $allowedGenerated) {
                    Add-Issue Error 'GENERATED_UNMANAGED_FILE' "V5.2.0 generated directory may contain only generated continuation/final-result views; found '$relative'."
                }
            }
        }
    }

    if ($currentState -in @('REVIEWING', 'CLOSING', 'COMPLETED')) {
        $reviewPath = Join-Path $taskDirectory.FullName 'codex-review.md'
        if (Test-Path -LiteralPath $reviewPath -PathType Leaf) {
            $reviewText = Get-Content -LiteralPath $reviewPath -Raw -Encoding UTF8
            $reviewFront = Get-FrontMatter -Text $reviewText
            if ($null -eq $reviewFront) {
                Add-Issue Error 'REVIEW_METADATA_MISSING' 'codex-review.md must contain structured review front matter.'
            }
            else {
                $reviewActor = Get-YamlNestedScalar -Text $reviewFront.Metadata -Parent 'review' -Name 'actor'
                $reviewDecision = Get-YamlNestedScalar -Text $reviewFront.Metadata -Parent 'review' -Name 'decision'
                $reviewEvidence = Get-YamlNestedScalar -Text $reviewFront.Metadata -Parent 'review' -Name 'evidence'
                $reviewTimestamp = Get-YamlNestedScalar -Text $reviewFront.Metadata -Parent 'review' -Name 'timestamp'
                $parsedReviewTime = [DateTimeOffset]::MinValue
                if ($reviewActor -ne 'tp-verification-engineering') { Add-Issue Error 'REVIEW_ACTOR_INVALID' "codex-review.md review.actor must be tp-verification-engineering, not '$reviewActor'." }
                if ($reviewDecision -notin @('PASS', 'FAIL', 'NEEDS_FIX')) { Add-Issue Error 'REVIEW_DECISION_INVALID' "codex-review.md review.decision '$reviewDecision' is invalid." }
                elseif ($reviewDecision -ne 'PASS') { Add-Issue Error 'REVIEW_NOT_PASS' "State '$currentState' requires review decision PASS from tp-verification-engineering." }
                if ([string]::IsNullOrWhiteSpace($reviewEvidence)) { Add-Issue Error 'REVIEW_EVIDENCE_MISSING' 'codex-review.md review.evidence is required.' }
                if (-not [DateTimeOffset]::TryParse($reviewTimestamp, [ref]$parsedReviewTime)) { Add-Issue Error 'REVIEW_TIME_INVALID' 'codex-review.md review.timestamp must be valid ISO 8601.' }

                if ($null -eq $latestReviewEvent) {
                    Add-Issue Error 'REVIEW_EVENT_MISSING' 'events.jsonl must contain REVIEW_COMPLETED with actor=tp-verification-engineering.'
                }
                else {
                    if ([string]$latestReviewEvent.decision -ne $reviewDecision) { Add-Issue Error 'REVIEW_EVENT_MISMATCH' 'REVIEW_COMPLETED decision does not match codex-review.md.' }
                    if ([string]$latestReviewEvent.time -ne $reviewTimestamp) { Add-Issue Error 'REVIEW_EVENT_MISMATCH' 'REVIEW_COMPLETED time does not match codex-review.md.' }
                    $eventEvidence = @($latestReviewEvent.evidence | ForEach-Object { [string]$_ })
                    if ($eventEvidence -notcontains $reviewEvidence) { Add-Issue Error 'REVIEW_EVENT_MISMATCH' 'REVIEW_COMPLETED evidence does not match codex-review.md.' }
                }
            }
        }
    }
}

if ($requiresClosingChain) {
    $acceptancePath = Join-Path $taskDirectory.FullName 'acceptance.md'
    if (Test-Path -LiteralPath $acceptancePath -PathType Leaf) {
        $acceptanceText = Get-Content -LiteralPath $acceptancePath -Raw -Encoding UTF8
        if ($acceptanceText -match '(?m)^\s*action:\s*["'']?DML["'']?\s*(?:#.*)?$') {
            $hasDmlEvidence = ($acceptanceText -match '(?m)^\s*dml_execution:\s*passed\s*$') -and ($acceptanceText -match '(?m)^\s*execution_evidence:\s*[^\s#]') -and ($acceptanceText -match '(?m)^\s*rollback_or_cleanup:\s*[^\s#]')
            $riskAccepted = ($acceptanceText -match '(?m)^\s*dml_residual_risk:\s*accepted\s*$') -and ($currentState -eq 'COMPLETED')
            if (-not $hasDmlEvidence -and -not $riskAccepted) {
                Add-Issue Error 'DML_EVIDENCE_MISSING' 'V5.2.0 DML acceptance requires execution evidence, result verification and rollback/cleanup; EXPLAIN or read-only evidence is insufficient.'
            }
        }
    }

    # V5.2.0 personal mode：COMPLETED 必须经过 tp-delivery-convergence CLOSING；不要求人员 APPROVE。
    if ($currentState -eq 'COMPLETED') {
        if ($currentOwner -ne 'tp-delivery-convergence') {
            Add-Issue Error 'COMPLETION_OWNER_INVALID' "V5.2.0 COMPLETED must be owned by tp-delivery-convergence, not '$currentOwner'."
        }
        if (-not $script:VisitedStates.ContainsKey('CLOSING')) {
            Add-Issue Error 'CLOSING_CHAIN_MISSING' 'V5.2.0 completion requires a CLOSING STATE event committed by tp-delivery-convergence.'
        }
    }

    # execution receipt 校验：路径、文件名、JSON 结构、审计字段、时间与哈希。
    $receiptsDirectory = Join-Path $taskDirectory.FullName 'evidence\receipts'
    if (Test-Path -LiteralPath $receiptsDirectory -PathType Container) {
        $seenReceiptIds = @{}
        foreach ($receiptFile in (Get-ChildItem -LiteralPath $receiptsDirectory -Force)) {
            if ($receiptFile.PSIsContainer) {
                Add-Issue Error 'RECEIPT_NAME_INVALID' "evidence/receipts may not contain directories: '$($receiptFile.Name)'."
                continue
            }
            if ($receiptFile.Name -cnotmatch '^REC-\d{8}T\d{6}Z-[0-9a-f]{32}\.json$') {
                Add-Issue Error 'RECEIPT_NAME_INVALID' "Receipt file '$($receiptFile.Name)' must match REC-<yyyyMMddTHHmmssZ>-<uuid>.json."
                continue
            }
            $receipt = $null
            try { $receipt = Get-Content -LiteralPath $receiptFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop }
            catch {
                Add-Issue Error 'RECEIPT_JSON_INVALID' "Receipt '$($receiptFile.Name)' is not valid JSON: $($_.Exception.Message)"
                continue
            }
            foreach ($field in @('receipt_id', 'schema_version', 'task_id', 'action_type', 'actor', 'authorized_by', 'authorization_scope', 'environment', 'action_sha256', 'result', 'timestamp', 'evidence_hash')) {
                if (-not ($receipt.PSObject.Properties.Name -contains $field) -or [string]::IsNullOrWhiteSpace([string]$receipt.$field)) {
                    Add-Issue Error 'RECEIPT_FIELD_MISSING' "Receipt '$($receiptFile.Name)' is missing required field '$field'."
                }
            }
            if (($receipt.PSObject.Properties.Name -contains 'task_id') -and -not [string]::IsNullOrWhiteSpace($taskId) -and [string]$receipt.task_id -ne $taskId) {
                Add-Issue Error 'RECEIPT_TASK_MISMATCH' "Receipt '$($receiptFile.Name)' task_id '$($receipt.task_id)' does not match task '$taskId'."
            }
            if ($receipt.PSObject.Properties.Name -contains 'receipt_id') {
                $receiptId = [string]$receipt.receipt_id
                if ($receiptId -ne [System.IO.Path]::GetFileNameWithoutExtension($receiptFile.Name)) {
                    Add-Issue Error 'RECEIPT_ID_MISMATCH' "Receipt '$($receiptFile.Name)' receipt_id must equal its file name."
                }
                if ($seenReceiptIds.ContainsKey($receiptId)) {
                    Add-Issue Error 'RECEIPT_ID_DUPLICATE' "Duplicate receipt_id '$receiptId'."
                }
                $seenReceiptIds[$receiptId] = $true
            }
            $receiptTime = [DateTimeOffset]::MinValue
            if (($receipt.PSObject.Properties.Name -contains 'timestamp') -and -not [DateTimeOffset]::TryParse([string]$receipt.timestamp, [ref]$receiptTime)) {
                Add-Issue Error 'RECEIPT_TIME_INVALID' "Receipt '$($receiptFile.Name)' timestamp must be valid ISO 8601."
            }
            foreach ($hashField in @('action_sha256', 'evidence_hash')) {
                if (($receipt.PSObject.Properties.Name -contains $hashField) -and -not [string]::IsNullOrWhiteSpace([string]$receipt.$hashField) -and
                    [string]$receipt.$hashField -cnotmatch '^sha256:[0-9a-f]{64}$') {
                    Add-Issue Error 'RECEIPT_HASH_INVALID' "Receipt '$($receiptFile.Name)' field '$hashField' must be sha256:<64 hex>."
                }
            }
        }
    }
}

if ($requiresArtifactContract -and $riskLevel -in @('L0', 'L1')) {
    $riskRulePath = Join-Path $script:BaseRoot 'governance\risk-rule.yaml'
    if (-not (Test-Path -LiteralPath $riskRulePath -PathType Leaf)) {
        $aiWorkDirectory = $taskDirectory.Parent
        while ($null -ne $aiWorkDirectory -and $aiWorkDirectory.Name -ne '.ai-work') { $aiWorkDirectory = $aiWorkDirectory.Parent }
        if ($null -ne $aiWorkDirectory) { $riskRulePath = Join-Path $aiWorkDirectory.FullName 'governance\risk-rule.yaml' }
    }
    $riskRules = Get-AutomatedRiskRules -Path $riskRulePath
    if ($null -eq $riskRules -or @($riskRules.Signals).Count -eq 0) {
        Add-Issue Error 'RISK_RULES_UNAVAILABLE' "automated risk rules cannot be loaded from '$riskRulePath'."
    }
    else {
        $riskInputs = @()
        foreach ($relative in @('task.md', 'implementation.md')) {
            $path = Join-Path $taskDirectory.FullName $relative
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                $lineNumber = 0
                foreach ($line in (Get-Content -LiteralPath $path -Encoding UTF8)) {
                    $lineNumber++
                    $candidate = $line.Trim()
                    if ([string]::IsNullOrWhiteSpace($candidate) -or $candidate -match '^(#|<!--|\|[-: ]+\||任务编号|维护角色)') { continue }
                    if ($candidate -match '^[-*]\s*[^：:]+[：:]\s*(?<value>.*)$') { $candidate = $Matches['value'].Trim() }
                    if ([string]::IsNullOrWhiteSpace($candidate) -or $candidate -in @('无', 'none', '不涉及')) { continue }
                    $riskInputs += [pscustomobject]@{ Source = "$relative`:$lineNumber"; Text = $candidate }
                }
            }
        }
        $handoffRiskPath = Join-Path $taskDirectory.FullName 'handoff.json'
        if (Test-Path -LiteralPath $handoffRiskPath -PathType Leaf) {
            try {
                $handoffRisk = Get-Content -LiteralPath $handoffRiskPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
                foreach ($change in @($handoffRisk.changes)) { $riskInputs += [pscustomobject]@{ Source = 'handoff.json:changes'; Text = [string]$change } }
            }
            catch { }
        }
        foreach ($eventNote in $riskEventLines) { $riskInputs += [pscustomobject]@{ Source = 'events.jsonl:SCOPE_CHANGE'; Text = [string]$eventNote } }

        $reportedSignals = @{}
        foreach ($input in $riskInputs) {
            # 契约按独立子句判断否定，否定只抵消同一子句内的信号。
            $segments = if ($requiresClosingChain) {
                @([regex]::Split($input.Text, '[，,。；;]') | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
            }
            else { @($input.Text) }
            foreach ($segment in $segments) {
                if (-not [string]::IsNullOrWhiteSpace($riskRules.NegativePattern) -and [regex]::IsMatch($segment, $riskRules.NegativePattern)) { continue }
                foreach ($signal in @($riskRules.Signals)) {
                    if ([regex]::IsMatch($segment, [string]$signal.Pattern) -and -not $reportedSignals.ContainsKey([string]$signal.Id)) {
                        $reportedSignals[[string]$signal.Id] = $true
                        Add-Issue Error 'RISK_SIGNAL_UNDERRATED' "risk_level '$riskLevel' is too low: signal '$($signal.Id)' matched $($input.Source)."
                    }
                }
            }
        }
    }
}

$acceptancePath = Join-Path $taskDirectory.FullName $artifactPaths['acceptance']
if (Test-Path -LiteralPath $acceptancePath -PathType Leaf) {
    $acceptanceRows = 0
    $validAcceptanceRows = 0
    $acceptanceRawText = Get-Content -LiteralPath $acceptancePath -Raw -Encoding UTF8
    $completionStates = @('CLOSING', 'COMPLETED')
    $deferredItems = @()
    $ownerWaivedItems = @()

    # 解析机器可读延期验收记录（deferred_acceptance 列表）。兼容 PyYAML safe_dump 的 2 空格子字段缩进。
    $deferredRecords = @{}
    # 个人模式：无 AC 时只接受机器可读的 no_acceptance_required 声明，不依赖人员批准或 receipt。
    $noAcceptanceRequired = $false
    $noAcceptanceBlock = [regex]::Match($acceptanceRawText, '(?ms)^no_acceptance_required:\s*\r?\n(?<body>(?:^\s{2,}[^\r\n]*(?:\r?\n|$))*)')
    if ($noAcceptanceBlock.Success) {
        $noAcceptanceBody = $noAcceptanceBlock.Groups['body'].Value
        $declared = [regex]::IsMatch($noAcceptanceBody, '(?mi)^\s+declared:\s*true\s*(?:#.*)?$')
        $reasonMatch = [regex]::Match($noAcceptanceBody, '(?mi)^\s+reason:\s*["'']?(?<reason>[^"''#\r\n]+)')
        if ($declared -and $reasonMatch.Success -and -not [string]::IsNullOrWhiteSpace($reasonMatch.Groups['reason'].Value)) {
            $noAcceptanceRequired = $true
        }
    }
    if ($requiresClosingChain) {
        $deferredBlock = [regex]::Match($acceptanceRawText, '(?ms)^deferred_acceptance:(?<body>.*?)(?=^```|\z)')
        if ($deferredBlock.Success) {
            foreach ($item in [regex]::Matches($deferredBlock.Groups['body'].Value, '(?m)^[ \t]*-[ \t]+ac:[ \t]*"?(?<ac>AC-[^"\r\n]+?)"?[ \t]*$(?<fields>(?:\r?\n[ \t]{2,}[a-z_]+:[^\r\n]*)*)')) {
                $deferredFields = @{}
                foreach ($fieldMatch in [regex]::Matches($item.Groups['fields'].Value, '(?m)^[ \t]{2,}(?<key>[a-z_]+):[ \t]*"?(?<value>[^"\r\n]*?)"?[ \t]*$')) {
                    $deferredFields[$fieldMatch.Groups['key'].Value] = $fieldMatch.Groups['value'].Value.Trim()
                }
                $deferredRecords[$item.Groups['ac'].Value.Trim()] = $deferredFields
            }
        }
    }
    $ownerWaiverRecords = @{}
    if ($requiresClosingChain) {
        $waiverBlock = [regex]::Match($acceptanceRawText, '(?ms)^owner_waivers:(?<body>.*?)(?=^```|\z)')
        if ($waiverBlock.Success) {
            foreach ($item in [regex]::Matches($waiverBlock.Groups['body'].Value, '(?m)^[ \t]*-[ \t]+ac:[ \t]*"?(?<ac>AC-[^"\r\n]+?)"?[ \t]*$(?<fields>(?:\r?\n[ \t]{2,}[a-z_]+:[^\r\n]*)*)')) {
                $fields = @{}
                foreach ($fieldMatch in [regex]::Matches($item.Groups['fields'].Value, '(?m)^[ \t]{2,}(?<key>[a-z_]+):[ \t]*"?(?<value>[^"\r\n]*?)"?[ \t]*$')) {
                    $fields[$fieldMatch.Groups['key'].Value] = $fieldMatch.Groups['value'].Value.Trim()
                }
                $ownerWaiverRecords[$item.Groups['ac'].Value.Trim()] = $fields
            }
        }
    }

    # 人工页面验收声明（page_verification 块）。V5.2.0 枚举：NOT_REQUIRED | human | verification | architecture（缺省视为无需页面验证）。
    $pageMode = ''
    $pageWitness = ''
    $pageWitnessEvidence = ''
    if ($requiresClosingChain) {
        $pageBlock = [regex]::Match($acceptanceRawText, '(?ms)^page_verification:\s*\r?\n(?<body>(?:^[ \t]+.*(?:\r?\n|$))*)')
        if ($pageBlock.Success) {
            $pageMode = [string](Get-YamlScalar -Text $pageBlock.Groups['body'].Value -Name 'mode')
            $pageWitness = [string](Get-YamlScalar -Text $pageBlock.Groups['body'].Value -Name 'human_witness')
            $pageWitnessEvidence = [string](Get-YamlScalar -Text $pageBlock.Groups['body'].Value -Name 'witness_evidence')
        }
        if (-not [string]::IsNullOrWhiteSpace($pageMode) -and $pageMode -notin @('NOT_REQUIRED', 'human', 'verification', 'architecture')) {
            Add-Issue Error 'PAGE_MODE_INVALID' "page_verification.mode '$pageMode' is invalid; V5.2.0 allows NOT_REQUIRED, human, verification, or architecture (or omit the block)."
        }
        if ($pageMode -eq 'human' -and $pageWitness -eq 'confirmed' -and [string]::IsNullOrWhiteSpace($pageWitnessEvidence)) {
            Add-Issue Error 'PAGE_WITNESS_EVIDENCE_MISSING' 'page_verification.human_witness=confirmed requires a non-empty witness_evidence.'
        }
    }

    # 标准八列验收表结构校验（验收矩阵首个表头行）。verdict 保持 $cells[8]。
    if ($requiresClosingChain) {
        $headerLine = $null
        foreach ($rawLine in ($acceptanceRawText -split "`r?`n")) {
            if ($rawLine -match '^\s*\|' -and $rawLine -notmatch '^\s*\|[\s\-:|]*$') { $headerLine = $rawLine; break }
        }
        if ($null -eq $headerLine) {
            Add-Issue Error 'ACCEPTANCE_HEADER_INVALID' 'acceptance.md has no acceptance matrix header row.'
        }
        else {
            $headerCells = $headerLine.Split('|') | ForEach-Object { $_.Trim() }
            if ($headerCells.Count -ne 10 -or -not $headerLine.Trim().StartsWith('|') -or -not $headerLine.Trim().EndsWith('|') -or
                $headerCells[1] -ne '编号' -or $headerCells[8] -ne '结论') {
                Add-Issue Error 'ACCEPTANCE_HEADER_INVALID' 'V5.2.0 acceptance matrix must use the standard eight-column header ending with the verdict column.'
            }
        }
    }

    foreach ($line in (Get-Content -LiteralPath $acceptancePath -Encoding UTF8)) {
        if ($line -notmatch '^\s*\|\s*(AC-[^|\s]+)\s*\|') {
            continue
        }

        $acceptanceRows++
        $cells = $line.Split('|') | ForEach-Object { $_.Trim() }
        $condition = if ($cells.Count -gt 2) { $cells[2] } else { '' }
        $evidence = if ($cells.Count -gt 6) { $cells[6] } else { '' }
        $verdict = if ($cells.Count -gt 8) { $cells[8] } else { '' }

        # 行结构校验：首尾分隔符 + 拆分后恰为 10 个单元格；错位表格明确失败。
        if ($requiresClosingChain) {
            $trimmedRow = $line.Trim()
            if (-not $trimmedRow.EndsWith('|') -or $cells.Count -ne 10) {
                Add-Issue Error 'ACCEPTANCE_ROW_STRUCTURE_INVALID' "Acceptance row '$($cells[1])' must keep leading/trailing pipes and exactly eight columns (10 split cells); found $($cells.Count)."
            }
        }

        # verdict 枚举校验（允许“：说明”后缀）。
        $verdictToken = ''
        $verdictMatch = [regex]::Match([string]$verdict, '^(PASS|NOT_REQUIRED|N/A|PENDING|BLOCKED|DEFERRED_ACCEPTED|OWNER_WAIVED)\b')
        if ($verdictMatch.Success) { $verdictToken = $verdictMatch.Groups[1].Value }
        if ($requiresClosingChain -and [string]::IsNullOrWhiteSpace($verdictToken)) {
            $level = if ($StrictAcceptanceStates -contains $currentState -or $currentState -eq 'VERIFYING') { 'Error' } else { 'Warning' }
            Add-Issue $level 'ACCEPTANCE_VERDICT_INVALID' "Acceptance item '$($cells[1])' verdict '$verdict' must start with PASS, NOT_REQUIRED, N/A, PENDING, BLOCKED, DEFERRED_ACCEPTED, or OWNER_WAIVED."
        }
        if ($verdictToken -eq 'DEFERRED_ACCEPTED') { $deferredItems += [string]$cells[1] }
        if ($verdictToken -eq 'OWNER_WAIVED') { $ownerWaivedItems += [string]$cells[1] }

        if ([string]::IsNullOrWhiteSpace($condition)) {
            $level = if ($StrictAcceptanceStates -contains $currentState) { 'Error' } else { 'Warning' }
            Add-Issue $level 'ACCEPTANCE_CONDITION_MISSING' "Acceptance item '$($cells[1])' has no condition."
        }
        else {
            $validAcceptanceRows++
        }

        if (-not [string]::IsNullOrWhiteSpace($condition) -and $verdictToken -eq 'PASS' -and [string]::IsNullOrWhiteSpace($evidence)) {
            $level = if ($StrictAcceptanceStates -contains $currentState) { 'Error' } else { 'Warning' }
            Add-Issue $level 'ACCEPTANCE_EVIDENCE_MISSING' "Acceptance item '$($cells[1])' has no evidence path."
        }

        if ($requiresHandoffGate -and $currentState -eq 'REVIEWING' -and $verdict -notin @('PASS', 'N/A', 'NOT_REQUIRED')) {
            Add-Issue Error 'ACCEPTANCE_NOT_CLOSED' "V4.1 review gate requires acceptance item '$($cells[1])' to be PASS, N/A, or NOT_REQUIRED."
        }

        # mode=human 且未确认人工见证时，human 见证项不得 PASS。
        if ($requiresClosingChain -and $pageMode -eq 'human' -and $pageWitness -ne 'confirmed' -and
            $cells.Count -gt 7 -and [string]$cells[7] -eq 'human' -and $verdictToken -eq 'PASS') {
            Add-Issue Error 'HUMAN_PAGE_PASS_INVALID' "page_verification.mode=human forbids PASS on human-witness item '$($cells[1])' before the human witness is confirmed."
        }

        # 完成态拒绝 PENDING/BLOCKED；DEFERRED_ACCEPTED 必须有完整审计记录。
        if ($requiresClosingChain -and $currentState -in $completionStates) {
            if ($verdictToken -in @('PENDING', 'BLOCKED')) {
                Add-Issue Error 'ACCEPTANCE_NOT_CLOSED' "Completion state '$currentState' forbids acceptance item '$($cells[1])' verdict '$verdictToken'."
            }
            elseif ($verdictToken -eq 'DEFERRED_ACCEPTED') {
                $acId = [string]$cells[1]
                if (-not $deferredRecords.ContainsKey($acId)) {
                    Add-Issue Error 'DEFERRED_RECORD_MISSING' "DEFERRED_ACCEPTED item '$acId' has no deferred_acceptance record; it is treated as PENDING."
                }
                else {
                    $deferredRecord = $deferredRecords[$acId]
                    $recordedAt = [DateTimeOffset]::MinValue
                    if (-not [DateTimeOffset]::TryParse([string]$deferredRecord['recorded_at'], [ref]$recordedAt)) {
                        Add-Issue Error 'DEFERRED_RECORD_MISSING' "Deferred item '$acId' requires a valid recorded_at timestamp."
                    }
                    foreach ($requiredField in @('residual_risk', 'reverify_owner', 'trigger')) {
                        if ([string]::IsNullOrWhiteSpace([string]$deferredRecord[$requiredField])) {
                            Add-Issue Error 'DEFERRED_RECORD_MISSING' "Deferred item '$acId' is missing required field '$requiredField'."
                        }
                    }
                }
            }
            elseif ($verdictToken -eq 'OWNER_WAIVED') {
                $acId = [string]$cells[1]
                if (-not $ownerWaiverRecords.ContainsKey($acId)) {
                    Add-Issue Error 'OWNER_WAIVER_RECORD_MISSING' "OWNER_WAIVED item '$acId' has no owner_waivers record."
                }
                else {
                    $waiver = $ownerWaiverRecords[$acId]
                    $recordedAt = [DateTimeOffset]::MinValue
                    if (-not [DateTimeOffset]::TryParse([string]$waiver['recorded_at'], [ref]$recordedAt)) {
                        Add-Issue Error 'OWNER_WAIVER_RECORD_MISSING' "Owner-waived item '$acId' requires a valid recorded_at timestamp."
                    }
                    foreach ($requiredField in @('reason', 'residual_risk', 'actor')) {
                        if ([string]::IsNullOrWhiteSpace([string]$waiver[$requiredField])) {
                            Add-Issue Error 'OWNER_WAIVER_RECORD_MISSING' "Owner-waived item '$acId' is missing required field '$requiredField'."
                        }
                    }
                    if ([string]$waiver['actor'] -ne 'human_owner') {
                        Add-Issue Error 'OWNER_WAIVER_RECORD_MISSING' "Owner-waived item '$acId' actor must be human_owner."
                    }
                }
            }
        }
    }

    if ($acceptanceRows -eq 0 -and -not $noAcceptanceRequired) {
        $level = if ($StrictAcceptanceStates -contains $currentState) { 'Error' } else { 'Warning' }
        Add-Issue $level 'ACCEPTANCE_ROWS_MISSING' 'acceptance.md has no AC rows and no valid no_acceptance_required declaration.'
    }
    elseif ($validAcceptanceRows -eq 0 -and $StrictAcceptanceStates -contains $currentState) {
        Add-Issue Error 'ACCEPTANCE_VALID_ROWS_MISSING' "State '$currentState' requires at least one non-empty acceptance item."
    }

    # 存在延期项时，结项摘要必须逐项列出。
    if ($requiresClosingChain -and $currentState -eq 'COMPLETED' -and @($deferredItems).Count -gt 0) {
        $finalResultPath = Join-Path $taskDirectory.FullName 'generated/final-result.md'
        if (Test-Path -LiteralPath $finalResultPath -PathType Leaf) {
            $finalFront = Get-FrontMatter -Text (Get-Content -LiteralPath $finalResultPath -Raw -Encoding UTF8)
            $finalBody = if ($null -ne $finalFront) { $finalFront.Content } else { '' }
            foreach ($deferredItem in $deferredItems) {
                if (-not $finalBody.Contains($deferredItem)) {
                    Add-Issue Error 'FINAL_DEFERRED_MISSING' "generated/final-result.md must list deferred acceptance item '$deferredItem'."
                }
            }
        }
    }
}

# Final Hardening（Task 4 §6.7）：统一 cli.validator 校验（Python 侧权威语义）。
# PowerShell 保留自身的 ShdDriver/M1-M2 等非规则类检查作为补充展示，规则类
# 判定（acceptance/codex-review/test-guide/scope/decisions）以 cli.validator 为准。
Invoke-PythonValidator -TaskDirectory $taskDirectory.FullName -CurrentState $currentState

# M4 定向过期提示：生成视图过期且 current_state 为带 ready 声明的产出态时，追加 HANDOFF_PENDING（不替换 GENERATED_* 码）
if ($requiresHandoffClosure -and -not [string]::IsNullOrWhiteSpace($currentState) -and $ShdDriverTable.ContainsKey($currentState)) {
    $staleCodes = @('GENERATED_SOURCE_NEWER', 'GENERATED_SOURCE_DIGEST_MISMATCH', 'GENERATED_CONTENT_DIGEST_MISMATCH')
    $hasStaleIssue = $false
    foreach ($issue in $script:Issues) {
        if ($issue.Code -in $staleCodes) { $hasStaleIssue = $true; break }
    }
    if ($hasStaleIssue) {
        $driver = $ShdDriverTable[$currentState]
        $artifactPath = Join-Path $taskDirectory.FullName $driver.artifact
        $decl = Get-ShdDeclaration -ArtifactPath $artifactPath -IsReview $driver.review
        if ($null -ne $decl -and $decl.Ready -and -not [string]::IsNullOrWhiteSpace($decl.FromState) -and $decl.FromState -eq $currentState) {
            Add-Issue Error 'HANDOFF_PENDING' "stage $currentState 已声明就绪但生成视图过期；先执行官方 commit --refresh 重建派生视图，再继续正式流转。不要手改 generated/*。"
        }
    }
}

$errorCount = @($script:Issues | Where-Object { $_.Level -eq 'Error' }).Count
$warningCount = @($script:Issues | Where-Object { $_.Level -eq 'Warning' }).Count

Write-Output 'TP-Spec-Coding task validation summary (V5.2.0 single active contract: artifacts, SHD closure, acceptance closure, receipts, closing chain)'
Write-Output "Task directory: $($taskDirectory.FullName)"
Write-Output "Task id: $taskId"
Write-Output "Current state: $currentState"
Write-Output "Current owner: $currentOwner"
Write-Output "Risk level: $riskLevel"
Write-Output "Work item count: $($workItems.Count)"
Write-Output "Errors: $errorCount; warnings: $warningCount"

foreach ($issue in $script:Issues) {
    Write-Output "[$($issue.Level)] $($issue.Code) - $($issue.Message)"
}

if ($errorCount -gt 0) {
    exit 1
}

exit 0
