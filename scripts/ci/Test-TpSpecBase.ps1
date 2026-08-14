<#
.SYNOPSIS
V5.2.1 P1 unified offline test entry (plan §5 B-02).

.DESCRIPTION
PowerShell dispatcher for the TP-Spec-Coding local test chain. Fully offline:
never touches network, external project directories, databases, browsers,
containers or credentials.

-Mode Static : P1 scope only — format policy, manifest hash recompute,
    forbidden paths, network-primitive blacklist, Python byte-compile and
    test discovery. Deliberately contains NO YAML semantic checks; those
    join only after the P2 controlled loader lands (ruling P0-3).
-Mode Full   : active V5.2.1 release gate only.
-Mode LegacyV510 : frozen prior-contract archive compatibility diagnostics; failures do not make the active V5.2.1 gate red.
-KeepWorkDir : by default the work directory created by THIS run (resolved
    and verified before removal) is cleaned; only this switch keeps it.
    Child scripts' own audit temp dirs are never touched.
-ReportPath  : writes the B-02 minimal JSON summary (version, mode, passed,
    failed, duration, artifact_contract, git_sha, items, workdir, artifact
    hashes). Must NOT point inside the version-controlled repository.
-BaseRoot    : repository root override, used by negative tests to point
    the checks at a tampered clone. Defaults to the real base.

Exit code 0 only if every check/suite passes; missing prerequisites (e.g.
python) fail loudly instead of being skipped.
#>
[CmdletBinding()]
param(
    [ValidateSet('Static', 'Full', 'LegacyV510')]
    [string]$Mode = 'Static',
    [switch]$KeepWorkDir,
    [string]$ReportPath = '',
    [string]$BaseRoot = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$realBase = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # tp-spec-base
if ([string]::IsNullOrWhiteSpace($BaseRoot)) { $base = $realBase }
else { $base = (Resolve-Path -LiteralPath $BaseRoot).Path }

$swTotal = [System.Diagnostics.Stopwatch]::StartNew()
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$script:Items = @()

function Add-Item2([string]$Name, [string]$Status, [int]$ExitCode, [long]$DurationMs, [string]$Detail = '') {
    $script:Items += [pscustomobject]@{
        name = $Name; status = $Status; exit_code = $ExitCode
        duration_ms = $DurationMs; detail = $Detail
    }
    $tag = if ($Status -eq 'PASS') { 'PASS' } else { 'FAIL' }
    Write-Output ("{0} {1} ({2} ms) {3}" -f $tag, $Name, $DurationMs, $Detail)
}

function Invoke-Check([string]$Name, [scriptblock]$Body) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $detail = & $Body
        Add-Item2 $Name 'PASS' 0 $sw.ElapsedMilliseconds ([string]$detail)
    }
    catch {
        Add-Item2 $Name 'FAIL' 1 $sw.ElapsedMilliseconds $_.Exception.Message
    }
}

# --- work directory (created by this run; the only dir we may clean) ---
$workDir = Join-Path ([System.IO.Path]::GetTempPath()) ("tpspec-ci-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + "-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $workDir -Force | Out-Null
Write-Output "WORKDIR $workDir"

# --- report path guard: never inside the version-controlled source tree ---
if (-not [string]::IsNullOrWhiteSpace($ReportPath)) {
    $reportFull = [System.IO.Path]::GetFullPath($ReportPath)
    if ($reportFull.StartsWith($realBase, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "ReportPath '$reportFull' is inside the version-controlled repository; reports must live outside (plan B-02)."
    }
}

# ==================== Static checks (P1 scope, no YAML semantics) ====================

Invoke-Check 'static.format.version_file' {
    $v = (Get-Content -LiteralPath (Join-Path $base 'VERSION') -Raw).Trim()
    if ($v -notmatch '^\d+\.\d+\.\d+$') { throw "VERSION '$v' is not major.minor.patch" }
    "VERSION=$v"
}

Invoke-Check 'static.format.byte_policy' {
    $ga = Get-Content -LiteralPath (Join-Path $base '.gitattributes') -Raw
    if ($ga -notmatch '(?m)^\*\s+-text') { throw ".gitattributes lacks '* -text' byte-exact policy (G1)" }
    $crlf = (& git -C $base config core.autocrlf 2>$null)
    if ([string]::IsNullOrWhiteSpace([string]$crlf)) { $crlf = '<unset>' }
    # Repository byte policy is authoritative. Hosted/user Git may set
    # core.autocrlf=true globally; '* -text' prevents checkout conversion, and
    # manifest verification proves the actual bytes. Keep autocrlf diagnostic-only.
    "* -text; core.autocrlf=$crlf (diagnostic only)"
}

Invoke-Check 'static.hash.manifest_recompute' {
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $out = & python (Join-Path $base 'scripts\update_manifest.py') --verify 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($code -ne 0) { throw ('manifest recompute failed: ' + (($out | Select-Object -First 5) -join ' | ')) }
    ($out | Select-Object -Last 1)
}

if ($Mode -eq 'Full') {
    Invoke-Check 'full.release.git_manifest' {
        $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        $out = & python (Join-Path $base 'scripts\update_manifest.py') --verify-release 2>&1
        $code = $LASTEXITCODE
        $ErrorActionPreference = $prevEap
        if ($code -ne 0) { throw ('release manifest gate failed: ' + (($out | Select-Object -First 8) -join ' | ')) }
        ($out | Select-Object -Last 1)
    }
}

Invoke-Check 'static.forbidden.paths' {
    $tracked = @(& git -C $base ls-files)
    # docs/ 已纳入 Git 管理（V5.2.1 发布完整性）；仅禁止运行时产物与本地状态
    $forbiddenPatterns = @('__pycache__', '\.pyc$', '^db/registry\.local\.json$', '\.db$', '\.flush-journal', '\.local\.', '\.pytest_cache', '^tp-spec-base\.zip$', '^docs/planning/')
    $hits = @()
    foreach ($p in $forbiddenPatterns) {
        $hits += @($tracked | Where-Object { $_ -match $p -and $_ -notmatch '\.example$' })
    }
    # bytecode must never be TRACKED; untracked __pycache__ from normal CLI use
    # is regenerable runtime residue and is cleaned at the end of this run
    if ($hits.Count -gt 0) { throw ("forbidden tracked paths present: " + (($hits | Select-Object -Unique) -join '; ')) }
    "no forbidden tracked paths"
}

Invoke-Check 'static.forbidden.network_primitives' {
    # patterns assembled at runtime so this file never matches itself
    $pats = @(
        ('Invoke-Web' + 'Request'), ('Invoke-Rest' + 'Method'),
        ('Net.' + 'WebClient'), ('Http' + 'Client'), ('Start-Bits' + 'Transfer'),
        ('urllib.' + 'request'), ('http.' + 'client'), ('requests.' + 'get'), ('socket.' + 'connect')
    )
    $scanRoots = @('scripts', 'cli') | ForEach-Object { Join-Path $base $_ }
    $hits = @()
    foreach ($root in $scanRoots) {
        $files = Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in @('.ps1', '.py') -and $_.FullName -ne $PSCommandPath }
        foreach ($f in $files) {
            foreach ($p in $pats) {
                if (Select-String -LiteralPath $f.FullName -SimpleMatch -Pattern $p -Quiet) { $hits += "$($f.Name):$p" }
            }
        }
    }
    if ($hits.Count -gt 0) { throw ("network primitives found: " + ($hits -join '; ')) }
    "no network primitives in scripts/ or cli/"
}

Invoke-Check 'static.python.compile' {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { throw 'python not found on PATH; offline prerequisite missing (fail, not skip)' }
    $targets = @((Join-Path $base 'cli'), (Join-Path $base 'scripts\tests')) | Where-Object { Test-Path $_ }
    $out = & python -m compileall -q @targets 2>&1
    if ($LASTEXITCODE -ne 0) { throw ("compileall failed: " + ($out -join ' | ')) }
    # never leave bytecode residue in the working tree
    Get-ChildItem -LiteralPath $targets -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force
    "compileall OK ($((& python --version 2>&1)))"
}

Invoke-Check 'static.tests.discovery' {
    $required = @(
        'scripts\tests\Test-RoleCatalog.ps1',
        'scripts\tests\Test-V510SingleContract.ps1',
        'scripts\tests\Test-V510FileMode.ps1',
        'scripts\tests\Test-V510DbGuard.ps1'
    )
    $missing = @($required | Where-Object { -not (Test-Path -LiteralPath (Join-Path $base $_)) })
    if ($missing.Count -gt 0) { throw ("regression scripts missing: " + ($missing -join '; ')) }
    $negatives = @(Get-ChildItem -LiteralPath (Join-Path $base 'scripts\ci') -Filter 'Test-NegativeCases.ps1' -ErrorAction SilentlyContinue)
    $switchNeg = @(Get-ChildItem -LiteralPath (Join-Path $base 'scripts\ci') -Filter 'Test-V510SwitchNegatives.ps1' -ErrorAction SilentlyContinue)
    "4 regression scripts + $($negatives.Count) negative suite(s) + $($switchNeg.Count) switch-negative suite(s) discovered"
}

# --- P2: YAML semantic checks now join Static (P1/P2 dependency resolved,
# ruling P0-3): the controlled loader + schemas exist, so every governed file
# is validated through the single controlled path. ---

Invoke-Check 'static.yaml.semantic_validate' {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { throw 'python not found; offline prerequisite missing' }
    $pairs = @(
        'governance/workflow.yaml|workflow',
        'governance/ai-role.yaml|ai-role',
        'governance/risk-rule.yaml|risk-rule',
        'governance/knowledge-rule.yaml|knowledge-rule',
        'governance/compat-matrix.yaml|compat-matrix',
        'governance/orchestration.yaml|orchestration',
        'agents/role-catalog.yaml|role-catalog',
        ((Join-Path 'templates' ((Get-Content -LiteralPath (Join-Path $base 'VERSION') -Raw).Trim())) + '/status.yaml|status-template')
    )
    $failed = @()
    foreach ($pair in $pairs) {
        $parts = $pair.Split('|')
        $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        & python (Join-Path $base 'cli\main.py') config validate --file $parts[0] --schema $parts[1] --base-root $base *> $null
        $code = $LASTEXITCODE
        $ErrorActionPreference = $prevEap
        if ($code -ne 0) { $failed += "$($parts[1])(exit $code)" }
    }
    Get-ChildItem -LiteralPath (Join-Path $base 'cli') -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    if ($failed.Count -gt 0) { throw ("YAML semantic validation failed: " + ($failed -join '; ')) }
    "8 governed files validated through controlled loader"
}

Invoke-Check 'static.unit.config_loader' {
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $out = & python (Join-Path $base 'scripts\tests\test_config_loader.py') 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    Get-ChildItem -LiteralPath (Join-Path $base 'cli') -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    $ran = ($out | Select-String -Pattern 'Ran (\d+) tests').Matches.Groups[1].Value
    if ($code -ne 0) { throw ("config loader unit tests failed: " + (($out | Select-String 'FAIL|Error' | Select-Object -First 3) -join ' | ')) }
    "config loader unit tests OK ($ran tests)"
}

if ($Mode -eq 'Full') {
    Invoke-Check 'full.python.pytest' {
        $py = Get-Command python -ErrorAction SilentlyContinue
        if (-not $py) { throw 'python not found; offline prerequisite missing' }
        $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        Push-Location $base
        try {
            $out = & python -m pytest -q 2>&1
            $code = $LASTEXITCODE
        }
        finally {
            Pop-Location
            $ErrorActionPreference = $prevEap
        }
        Get-ChildItem -LiteralPath @((Join-Path $base 'cli'), (Join-Path $base 'scripts')) -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        if ($code -ne 0) { throw ("pytest failed: " + (($out | Select-Object -Last 12) -join ' | ')) }
        ($out | Select-Object -Last 1)
    }
}

# ==================== Full mode: dispatch existing suites ====================

if ($Mode -eq 'Full') {
    # Active V5.2.1 release gate.  Frozen V5.1.0 suites are intentionally not
    # part of the default release result; run -Mode LegacyV510 for archive
    # compatibility diagnostics.
    $suites = @(
        @{ Name = 'suite.role_catalog'; Path = 'scripts\tests\Test-RoleCatalog.ps1' }
    )
    $negPath = Join-Path $base 'scripts\ci\Test-NegativeCases.ps1'
    if (Test-Path -LiteralPath $negPath) {
        $suites += @{ Name = 'suite.negative_cases'; Path = 'scripts\ci\Test-NegativeCases.ps1' }
    }
}
elseif ($Mode -eq 'LegacyV510') {
    $suites = @(
        @{ Name = 'legacy.single_contract'; Path = 'scripts\tests\Test-V510SingleContract.ps1' },
        @{ Name = 'legacy.file_mode';       Path = 'scripts\tests\Test-V510FileMode.ps1' },
        @{ Name = 'legacy.db_guard';        Path = 'scripts\tests\Test-V510DbGuard.ps1' }
    )
    $switchNegPath = Join-Path $base 'scripts\ci\Test-V510SwitchNegatives.ps1'
    if (Test-Path -LiteralPath $switchNegPath) {
        $suites += @{ Name = 'legacy.switch_negatives'; Path = 'scripts\ci\Test-V510SwitchNegatives.ps1' }
    }
}
else { $suites = @() }

if ($Mode -in @('Full','LegacyV510')) {
    foreach ($s in $suites) {
        $full = Join-Path $base $s.Path
        $log = Join-Path $workDir ($s.Name + '.log')
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        Write-Output "RUN  $($s.Name) -> $($s.Path)"
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & powershell -NoProfile -ExecutionPolicy Bypass -File $full *> $log
        $code = $LASTEXITCODE
        $ErrorActionPreference = $prevEap
        $status = if ($code -eq 0) { 'PASS' } else { 'FAIL' }
        $passCnt = @(Select-String -LiteralPath $log -Pattern '^PASS ' -ErrorAction SilentlyContinue).Count
        $failCnt = @(Select-String -LiteralPath $log -Pattern '^FAIL ' -ErrorAction SilentlyContinue).Count
        Add-Item2 $s.Name $status $code $sw.ElapsedMilliseconds "checks: $passCnt pass / $failCnt fail; log: $($s.Name).log"
    }
}

# ==================== summary + report ====================

$passed = @($script:Items | Where-Object status -eq 'PASS').Count
$failed = @($script:Items | Where-Object status -ne 'PASS').Count
$gitSha = (& git -C $realBase rev-parse HEAD 2>$null)
$contract = (Get-Content -LiteralPath (Join-Path $realBase 'VERSION') -Raw).Trim()

# hash key intermediate artifacts (logs) before any cleanup
$artifactHashes = @{}
Get-ChildItem -LiteralPath $workDir -File -ErrorAction SilentlyContinue | ForEach-Object {
    $artifactHashes[$_.Name] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
}

$swTotal.Stop()
$report = [ordered]@{
    version           = '1.0.0'
    mode              = $Mode
    passed            = $passed
    failed            = $failed
    duration          = [math]::Round($swTotal.Elapsed.TotalSeconds, 3)
    artifact_contract = $contract
    git_sha           = $gitSha
    items             = $script:Items
    workdir           = $workDir
    workdir_kept      = [bool]$KeepWorkDir
    artifact_hashes   = $artifactHashes
}
if (-not [string]::IsNullOrWhiteSpace($ReportPath)) {
    $json = $report | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText([System.IO.Path]::GetFullPath($ReportPath), $json, $utf8NoBom)
    Write-Output "REPORT $ReportPath"
}

Write-Output ("SUMMARY mode={0} passed={1} failed={2} duration={3}s git={4}" -f $Mode, $passed, $failed, $report.duration, $gitSha)

# hygiene: remove regenerable bytecode residue produced by this run's python calls
foreach ($r in @('cli', 'scripts')) {
    Get-ChildItem -LiteralPath (Join-Path $base $r) -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

# cleanup: only the directory this run created, resolved and verified
if (-not $KeepWorkDir) {
    $resolved = (Resolve-Path -LiteralPath $workDir -ErrorAction SilentlyContinue)
    $tempRoot = [System.IO.Path]::GetTempPath().TrimEnd('\')
    if ($resolved -and $resolved.Path.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $resolved.Path).StartsWith('tpspec-ci-')) {
        Remove-Item -LiteralPath $resolved.Path -Recurse -Force
        Write-Output "CLEANED $($resolved.Path)"
    }
}
else {
    Write-Output "KEPT $workDir"
}

if ($failed -gt 0) { exit 1 } else { exit 0 }
