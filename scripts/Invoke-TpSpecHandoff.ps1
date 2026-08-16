<#
.SYNOPSIS
    TP-Spec-Coding V5.2.3 交接编排包装器
.DESCRIPTION
    检测 DB 后端是否启用：
    - 启用：projection rebuild → Invoke-TpSpecHandoffFlush.ps1 → event sync（顺序不可反）
    - 未启用：直接透传 Invoke-TpSpecHandoffFlush.ps1
.PARAMETER TaskPath
    任务目录路径（必需）
.PARAMETER Actor
    执行角色：tp-* 工作流角色或 human_owner（必需）
.PARAMETER DbBackend
    显式启用 DB 编排路径（缺省自动检测 config 表 db_backend_enabled；
    检测无可信结论时 fail-closed 拒绝，exit 9）
.EXAMPLE
    .\tp-spec.ps1 -TaskPath .tp-spec\tasks\TASK-DEMO-001 -Actor tp-development-engineering
.EXAMPLE
    .\tp-spec.ps1 -TaskPath .tp-spec\tasks\TASK-DEMO-001 -Actor tp-development-engineering -DbBackend
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$TaskPath,
    [Parameter(Mandatory=$true)]
    [ValidateSet('tp-product-design','tp-architecture-design','tp-development-engineering','tp-verification-engineering','tp-delivery-convergence','human_owner')]
    [string]$Actor,
    [switch]$DbBackend
)

$ErrorActionPreference = 'Stop'
$baseRoot = $PSScriptRoot | Split-Path
Set-Location -LiteralPath $baseRoot

# 解析 task_id（目录名）
$taskId = Split-Path -Leaf $TaskPath
if (-not $taskId) {
    throw "无法从 TaskPath 解析 task_id: $TaskPath"
}

$flushScript = Join-Path $baseRoot 'scripts\Invoke-TpSpecHandoffFlush.ps1'

# 检测 DB 后端是否启用（三值裁决，2026-07-30 BUG 修复）：
# - 明确 true  → rebuild → flush → sync 编排路径
# - 明确 false → 文件模式透传 flush
# - error/空输出/Python 缺失/库或注册表异常 → fail-closed 拒绝（exit 9），
#   不 rebuild、不 flush、不 sync、不写任何任务工件。若此处 fail-safe 误入
#   未启用路径，会带着豁免标记调用 flush 绕过底层守卫，重现账本割裂。
$enabled = $false
if ($DbBackend) {
    $enabled = $true
} else {
    $detectScript = @"
import sys, os
sys.path.insert(0, r'$baseRoot')
try:
    from cli import db as dbmod
    db_path = dbmod.resolve_db_path(task_id='$taskId')
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
    # G1 治本延伸：python -c 传多行 here-string 时，PowerShell 的 CRLF 会导致
    # Python 语法解析错误。改为写临时 .py 文件再执行，确保检测脚本正确运行。
    $detectFile = Join-Path ([System.IO.Path]::GetTempPath()) ('tp-spec-detect-' + [guid]::NewGuid().ToString('N') + '.py')
    $detectVerdict = ''
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        [System.IO.File]::WriteAllText($detectFile, $detectScript, (New-Object System.Text.UTF8Encoding($false)))
        $detectOutput = & python $detectFile 2>$null
        if ($null -ne $detectOutput) { $detectVerdict = ([string](@($detectOutput) -join "`n")).Trim() }
    } catch {
        $detectVerdict = 'error: ' + $_.Exception.Message
    } finally {
        $ErrorActionPreference = $prevEAP
        Remove-Item -LiteralPath $detectFile -Force -ErrorAction SilentlyContinue
    }
    if ($detectVerdict -match '^true') {
        $enabled = $true
    }
    elseif ($detectVerdict -notmatch '^false') {
        # fail-closed：检测无可信结论时拒绝，不得误入任何编排路径。
        # 用 [Console]::Error 输出（Write-Error 在 EAP=Stop 下会提前终止，exit 码失效）。
        $detectDetail = if ([string]::IsNullOrWhiteSpace($detectVerdict)) { 'no output; python missing or failed to start' } else { $detectVerdict }
        [Console]::Error.WriteLine("[tp-spec] DB-backend detection did not produce a trusted verdict for task '$taskId' ($detectDetail).")
        [Console]::Error.WriteLine("[tp-spec] Fail-closed: rebuild/flush/sync are all skipped and no task artifact is written, to prevent silent file/SQLite ledger drift.")
        [Console]::Error.WriteLine("[tp-spec] Fix the Python/DB/registry environment and retry.")
        exit 9
    }
}

if (-not $enabled) {
    # 未启用路径：透传 flush（行为与今天逐字节一致）
    # 守卫豁免：包装器已完成 DB 检测，flush 不再二次检测（单一决策点）；
    # 保存并恢复旧值，避免嵌套调用时污染父环境
    $prevOrchestrated = $env:TP_SPEC_ORCHESTRATED
    $env:TP_SPEC_ORCHESTRATED = '1'
    try {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $flushScript -TaskPath $TaskPath -Actor $Actor
        $passExit = $LASTEXITCODE
    } finally {
        if ($null -eq $prevOrchestrated) { Remove-Item Env:TP_SPEC_ORCHESTRATED -ErrorAction SilentlyContinue }
        else { $env:TP_SPEC_ORCHESTRATED = $prevOrchestrated }
    }
    exit $passExit
}

# 启用路径：rebuild → flush → sync（顺序不可反）
Write-Host "[tp-spec] DB 后端已启用，执行 rebuild → flush → sync"

# 1. projection rebuild（DB → status.yaml/events.jsonl）
& python cli/main.py projection rebuild --task $taskId --task-dir $TaskPath 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    # [Console]::Error 输出：Write-Error 在 EAP=Stop 下会提前终止，exit 8 失效。
    [Console]::Error.WriteLine("[tp-spec] projection rebuild 失败 (exit=$LASTEXITCODE)，不调 flush")
    exit 8
}

# 2. flush（生成 generated/continuation.md）
# 守卫豁免：flush 由本编排器调用，rebuild 已完成、sync 紧随其后；
# 保存并恢复旧值，避免嵌套调用时污染父环境
$prevOrchestrated = $env:TP_SPEC_ORCHESTRATED
$env:TP_SPEC_ORCHESTRATED = '1'
try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $flushScript -TaskPath $TaskPath -Actor $Actor
    $flushExit = $LASTEXITCODE
} finally {
    if ($null -eq $prevOrchestrated) { Remove-Item Env:TP_SPEC_ORCHESTRATED -ErrorAction SilentlyContinue }
    else { $env:TP_SPEC_ORCHESTRATED = $prevOrchestrated }
}
if ($flushExit -ne 0) {
    # [Console]::Error 输出：Write-Error 在 EAP=Stop 下会提前终止，透传退出码失效。
    [Console]::Error.WriteLine("[tp-spec] flush 失败 (exit=$flushExit)，不回流")
    exit $flushExit
}

# 3. event sync（回流 flush 追加事件到 DB）
& python cli/main.py event sync --task $taskId --task-dir $TaskPath 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Warning "[tp-spec] event sync 失败 (exit=$LASTEXITCODE)，flush 已成功，可重试 'event sync'"
    exit 7
}

Write-Host "[tp-spec] 交接完成：rebuild → flush → sync 全部成功"
exit 0
