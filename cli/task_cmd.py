# -*- coding: utf-8 -*-
"""TP-Spec-Coding V5.1 task 命令组（M1）。

包含：
- task create / get / list / transition / validate

核心保证：
- task transition 单事务（更新 task + 插入 task_event）
- transition 校验 workflow.yaml 合法 next
- --owner-role 缺省 = 目标状态规范 owner（与 Test-TpSpecTask.ps1 CANONICAL_OWNER_MISMATCH 对齐）
- COMPLETED 由自动质量门禁决定，不要求最终人工审批
- 用户确认仅用于产品/范围交互，不作为普通结单安全门禁
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import uuid
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import db as dbmod
from . import workflow_loader
from .frontmatter import FRONTMATTER_RE
from .environment import EnvironmentConfigError, load_project_binding
from .path_identity import same_path
from .version import active_version
from .workflow_loader import WorkflowLoadError

INITIAL_TASK_OWNER = "tp-software-lifecycle"

# task_id 格式：TASK-开头，后跟字母数字._-
_TASK_ID_RE = re.compile(r"^TASK-[A-Za-z0-9][A-Za-z0-9._-]*$")

# risk/flow 等级
_RISK_LEVELS = ("L0", "L1", "L2", "L3")

# Frozen long-state SHD compatibility table. Active V5.2.6 Record-first tasks return through the fast path and do not use this table.
_SHD_TRANSITIONS: Dict[str, List[str]] = {
    "NEW": ["RISK_ANALYZING", "TECH_DESIGNING", "DEVELOPING", "CANCELLED"],
    "RISK_ANALYZING": ["REQUIREMENT_CLARIFYING", "PRODUCT_DESIGNING", "TECH_DESIGNING", "DEVELOPING", "TECHNICAL_DISCOVERY"],
    "REQUIREMENT_CLARIFYING": ["PRODUCT_DESIGNING", "TECH_DESIGNING", "TECHNICAL_DISCOVERY", "CHANGE_CONFIRMING", "BLOCKED"],
    "TECHNICAL_DISCOVERY": ["REQUIREMENT_CLARIFYING", "TECH_DESIGNING", "DISCOVERY_REVIEW_REQUIRED", "BLOCKED"],
    "PRODUCT_DESIGNING": ["PRODUCT_CONFIRMING"],
    "PRODUCT_CONFIRMING": ["TECH_DESIGNING", "CANCELLED"],
    "TECH_DESIGNING": ["DEVELOPING", "CHANGE_CONFIRMING", "BLOCKED"],
    "DISCOVERY_REVIEW_REQUIRED": ["REQUIREMENT_CLARIFYING", "TECH_DESIGNING", "CHANGE_CONFIRMING", "DEVELOPING", "BLOCKED"],
    "CHANGE_CONFIRMING": ["REQUIREMENT_CLARIFYING", "PRODUCT_DESIGNING", "TECH_DESIGNING", "CANCELLED"],
    "BLOCKED": ["REQUIREMENT_CLARIFYING", "TECHNICAL_DISCOVERY", "TECH_DESIGNING", "DEVELOPING", "VERIFYING", "CANCELLED"],
    "DEVELOPING": ["ASSISTING", "VERIFYING", "DISCOVERY_REVIEW_REQUIRED", "BLOCKED"],
    "ASSISTING": ["VERIFYING", "DISCOVERY_REVIEW_REQUIRED", "BLOCKED"],
    "VERIFYING": ["DEVELOPING", "BROWSER_VERIFYING", "REVIEWING", "CLOSING", "DISCOVERY_REVIEW_REQUIRED", "BLOCKED"],
    "BROWSER_VERIFYING": ["REVIEWING", "CLOSING", "DISCOVERY_REVIEW_REQUIRED", "BLOCKED"],
    "REVIEWING": ["CLOSING", "DEVELOPING", "DISCOVERY_REVIEW_REQUIRED", "BLOCKED"],
    "CLOSING": ["COMPLETED", "BLOCKED"],
}

# Frozen SHD compatibility driver: from_state -> (artifact, is_verification)
_SHD_DRIVER: Dict[str, Tuple[str, bool]] = {
    "TECH_DESIGNING": ("task.md", False),
    "DEVELOPING": ("implementation.md", False),
    "ASSISTING": ("implementation.md", False),
    "VERIFYING": ("codex-review.md", True),
}

# Frozen SHD compatibility forward-consumer set
_SHD_FORWARD_CONSUMERS: Dict[str, List[str]] = {
    "TECH_DESIGNING": ["DEVELOPING", "ASSISTING", "VERIFYING", "BROWSER_VERIFYING", "REVIEWING", "CLOSING", "COMPLETED"],
    "DEVELOPING": ["VERIFYING", "BROWSER_VERIFYING", "REVIEWING", "CLOSING", "COMPLETED"],
    "ASSISTING": ["VERIFYING", "BROWSER_VERIFYING", "REVIEWING", "CLOSING", "COMPLETED"],
    "VERIFYING": ["REVIEWING", "CLOSING", "COMPLETED"],
}

# V5.2.6 A-01：front matter 解析统一走 cli/frontmatter.py（LF/CRLF/BOM 兼容）
_FM_RE = FRONTMATTER_RE

# HPB: next_prompt 必须完整的 12 字段
_HPB_REQUIRED_FIELDS = (
    "target_role", "target_state", "invocation", "task_id",
    "risk_level", "page_verification", "entry", "reading_order",
    "actions", "constraints", "exit_expectation", "fact_source_disclaimer",
)


def _resolve_owner(wf, state: str, risk_level: str, flow_level: str) -> Optional[str]:
    """解析目标态的规范 owner；COMPLETED 用 risk/flow 分支。"""
    if state == "COMPLETED":
        return wf.get_completion_owner(risk_level, flow_level)
    return wf.get_state_owner(state)


def _yaml_scalar(text: str, name: str) -> Optional[str]:
    m = re.search(
        r"(?m)^[ \t]*" + re.escape(name) + r"[ \t]*:[ \t]*(?P<value>[^#\r\n]*)(?:[ \t]*#.*)?\r?$",
        text,
    )
    if not m:
        return None
    return m.group("value").strip().strip('"').strip("'")


def _yaml_nested_scalar(text: str, parent: str, name: str) -> Optional[str]:
    m = re.match(
        r"(?ms)^" + re.escape(parent) + r":[ \t]*\r?\n(?P<body>(?:^[ \t]+.*(?:\r?\n|$))*)",
        text,
    )
    if not m:
        return None
    return _yaml_scalar(m.group("body"), name)


def _parse_shd(artifact_path: str, is_review: bool) -> Optional[Dict[str, str]]:
    """解析工件 front-matter 中的 stage_handoff 或 review 块。"""
    if not os.path.isfile(artifact_path):
        return None
    with open(artifact_path, "r", encoding="utf-8") as f:
        text = f.read()
    m = _FM_RE.match(text)
    if not m:
        return None
    body = m.group("body")
    if is_review:
        decision = _yaml_nested_scalar(body, "review", "decision")
        intended = _yaml_nested_scalar(body, "review", "next_state")
        return {
            "ready": "true" if decision == "PASS" else "false",
            "status": decision or "",
            "intended_next": intended or "",
            "from_state": "VERIFYING",
        }
    status = _yaml_nested_scalar(body, "stage_handoff", "status")
    intended = _yaml_nested_scalar(body, "stage_handoff", "intended_next")
    from_state = _yaml_nested_scalar(body, "stage_handoff", "from_state")
    return {
        "ready": "true" if status == "ready" else "false",
        "status": status or "",
        "intended_next": intended or "",
        "from_state": from_state or "",
    }


def _check_shd_closure(
    task_dir: str,
    current_state: str,
    visited_states: set,
    wf: Optional[Any] = None,
    risk_level: str = "",
    flow_level: str = "",
) -> List[str]:
    """SHD M1/M2 + HPB 校验（V5.2.6），返回错误消息列表。"""
    errors: List[str] = []
    # M1 反向一致性
    if current_state in _SHD_DRIVER:
        artifact, is_review = _SHD_DRIVER[current_state]
        decl = _parse_shd(os.path.join(task_dir, artifact), is_review)
        if decl and decl["from_state"] == current_state:
            if decl["ready"] == "true":
                errors.append(
                    f"HANDOFF_PENDING: stage {current_state} 已声明就绪但状态未推进，请执行 flush / task transition。"
                )
                # HPB: 交接提示词绑定
                ho_path = os.path.join(task_dir, "handoff.json")
                np = None
                try:
                    with open(ho_path, "r", encoding="utf-8") as f:
                        ho = json.load(f)
                    if isinstance(ho, dict) and "next_prompt" in ho:
                        np = ho["next_prompt"]
                except (OSError, json.JSONDecodeError, TypeError):
                    pass
                if not isinstance(np, dict):
                    errors.append(
                        f"HANDOFF_PROMPT_MISSING: stage {current_state} 已声明就绪，但缺少面向下一角色的可复制接续提示词，交接前必须补齐。"
                    )
                else:
                    missing = [
                        f for f in _HPB_REQUIRED_FIELDS
                        if not np.get(f) or (isinstance(np.get(f), (list, str)) and len(np.get(f)) == 0)
                    ]
                    if missing:
                        errors.append(
                            f"HANDOFF_PROMPT_MISSING: stage {current_state} 已声明就绪，但 next_prompt 缺少字段：{', '.join(missing)}。"
                        )
                    else:
                        intended = decl["intended_next"]
                        if str(np.get("target_state", "")) != intended:
                            errors.append(
                                f"HANDOFF_PROMPT_TARGET_MISMATCH: next_prompt.target_state '{np.get('target_state')}' 必须等于 intended_next '{intended}'。"
                            )
                        if wf is not None and intended:
                            expected_role = _resolve_owner(wf, intended, risk_level, flow_level)
                            if expected_role and str(np.get("target_role", "")) != expected_role:
                                errors.append(
                                    f"HANDOFF_PROMPT_TARGET_MISMATCH: next_prompt.target_role '{np.get('target_role')}' 必须是目标态 '{intended}' 的规范 owner '{expected_role}'。"
                                )
            intended = decl["intended_next"]
            if intended and current_state in _SHD_TRANSITIONS and intended not in _SHD_TRANSITIONS[current_state]:
                errors.append(
                    f"HANDOFF_NEXT_ILLEGAL: stage {current_state} 的 intended_next '{intended}' 不是合法后继。"
                )
    # M2 前向完整性
    for from_state, (artifact, is_review) in _SHD_DRIVER.items():
        if from_state not in visited_states:
            continue
        consumers = _SHD_FORWARD_CONSUMERS.get(from_state, [])
        if current_state not in consumers:
            continue
        decl = _parse_shd(os.path.join(task_dir, artifact), is_review)
        if not decl or not decl["from_state"] or decl["from_state"] != from_state:
            continue
        if decl["ready"] != "true":
            errors.append(
                f"HANDOFF_DECL_MISSING: 状态 '{current_state}' 需要 '{artifact}' 的就绪声明（from_state={from_state}），但 status 仍为 draft/未声明 ready。"
            )
        else:
            intended = decl["intended_next"]
            if intended and from_state in _SHD_TRANSITIONS and intended not in _SHD_TRANSITIONS[from_state]:
                errors.append(
                    f"HANDOFF_NEXT_ILLEGAL: stage {from_state} 的 intended_next '{intended}' 不是合法后继。"
                )
    return errors




_INTAKE_ARTIFACTS = (
    ("requirement.md", "requirement.md"),
    # One-time source compatibility: old pre-task requirement facts are adopted
    # into the v5.2.6 canonical requirement artifact, never copied as a second
    # active requirement model.
    ("requirement-knowledge.md", "requirement.md"),
    ("requirement-clarifications.md", "requirement-clarifications.md"),
    ("requirement-decisions.md", "requirement-decisions.md"),
)


def _adopt_intake_artifacts(scaffold_dir: Path, intake_dir: Path, task_id: str, adopted_at: str) -> List[str]:
    """Copy recognized pre-task requirement artifacts into a fresh task scaffold.

    Business prose is preserved. Runtime-owned identity/contract fields are normalized and
    provenance is appended to front matter. The source intake directory is never deleted.
    """
    intake_dir = intake_dir.resolve()
    if not intake_dir.is_dir():
        raise ValueError(f"intake directory not found: {intake_dir}")
    adopted: List[str] = []
    for source_name, target_name in _INTAKE_ARTIFACTS:
        src = intake_dir / source_name
        if not src.is_file():
            continue
        raw = src.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(f"intake artifact must be UTF-8: {src}") from exc
        # V5.2.6 Record-first: business roles own content, Runtime owns machine metadata.
        # Missing/mismatched front matter is normalized instead of sending the role
        # through a bookkeeping retry loop.
        artifact_type = target_name[:-3]
        if not text.startswith("---"):
            text = (
                "---\n"
                f"artifact: {artifact_type}\n"
                f'task_id: "{task_id}"\n'
                "artifact_contract:\n"
                f'  version: "{active_version()}"\n'
                "---\n\n" + text
            )
        fm_end = text.find("\n---", 3)
        if fm_end < 0:
            raise ValueError(f"intake artifact front matter is not closed: {src}")
        front = text[:fm_end]
        body = text[fm_end:]
        if re.search(r'(?m)^artifact:\s*.*$', front):
            front = re.sub(r'(?m)^artifact:\s*.*$', f'artifact: {artifact_type}', front, count=1)
        else:
            front = front.replace("---\n", f"---\nartifact: {artifact_type}\n", 1)
        if re.search(r'(?m)^task_id:\s*.*$', front):
            front = re.sub(r'(?m)^task_id:\s*.*$', f'task_id: "{task_id}"', front, count=1)
        else:
            front = front.replace("---\n", f'---\ntask_id: "{task_id}"\n', 1)
        text = front + body
        text = _replace_artifact_contract_version(text, active_version())
        if not re.search(r'(?ms)^artifact_contract:\s*\n\s+version:', text):
            fm_end = text.find("\n---", 3)
            text = text[:fm_end] + f'\nartifact_contract:\n  version: "{active_version()}"' + text[fm_end:]

        digest = hashlib.sha256(raw).hexdigest()
        fm_end = text.find("\n---", 3)
        provenance = (
            "\nintake_provenance:\n"
            f"  source_file: {json.dumps(source_name, ensure_ascii=False)}\n"
            f"  source_sha256: {json.dumps('sha256:' + digest)}\n"
            f"  adopted_at: {json.dumps(adopted_at)}\n"
            "  policy: copy_preserve_source\n"
        )
        if "\nintake_provenance:\n" not in text[:fm_end]:
            text = text[:fm_end] + provenance + text[fm_end:]
        target = scaffold_dir / target_name
        # Prefer the canonical requirement.md when both canonical and legacy
        # source names are present; do not let the legacy alias overwrite it.
        if target.exists() and source_name != target_name:
            continue
        target.write_text(text, encoding="utf-8", newline="\n")
        if target_name not in adopted:
            adopted.append(target_name)
    if not adopted:
        raise ValueError(
            "intake contains no supported requirement artifacts; expected one of: "
            + ", ".join(source for source, _ in _INTAKE_ARTIFACTS)
        )
    return adopted


_TASK_CREATE_TX_SCHEMA = "tp-spec.task-create/v1"
_TASK_CREATE_TX_NAME = "create-transaction.json"


def _task_create_workspace_root(args, project_id: str) -> Optional[Path]:
    """Return the workspace root when the invocation provides enough proof.

    Modern project bindings and canonical ``.tp-spec/tasks/<task>`` locations are
    authoritative enough for a mutation-time identity check.  Legacy/custom task
    layouts without either signal keep their existing behavior rather than guessing.
    """
    task_dir_arg = getattr(args, "task_dir", None)
    if task_dir_arg:
        task_dir = Path(task_dir_arg).resolve()
        parent = task_dir.parent
        if parent.name == "tasks" and parent.parent.name == ".tp-spec":
            return parent.parent.parent.resolve()

    cwd = Path.cwd().resolve()
    try:
        binding = load_project_binding(cwd)
    except EnvironmentConfigError:
        return None
    if binding.exists and binding.project_id == project_id:
        return cwd
    return None


def _task_create_marker_path(task_dir: Path) -> Path:
    return task_dir / ".tp-spec" / _TASK_CREATE_TX_NAME


def _write_task_create_marker(task_dir: Path, payload: Dict[str, Any]) -> Path:
    marker = _task_create_marker_path(task_dir)
    marker.parent.mkdir(parents=True, exist_ok=True)
    tmp = marker.with_name(f".{marker.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, marker)
    return marker


def _recover_interrupted_task_create(
    conn, task_dir: Path, *, task_id: str, project_id: str, db_path: str
) -> str:
    """Recover only a scaffold proven to belong to an interrupted task create.

    If SQLite has no matching task row, the marked scaffold is an uncommitted
    projection and is removed so the create can be retried.  If SQLite already has
    the task, only the stale marker is removed.  Unmarked/malformed directories are
    never guessed about and remain fail-closed through normal scaffold preflight.
    """
    marker = _task_create_marker_path(task_dir)
    if not marker.is_file():
        return ""
    try:
        payload = json.loads(marker.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict) or payload.get("schema") != _TASK_CREATE_TX_SCHEMA:
        return ""
    if str(payload.get("task_id") or "") != task_id or str(payload.get("project_id") or "") != project_id:
        return ""
    marker_db = str(payload.get("db_path") or "").strip()
    if not marker_db or not same_path(marker_db, db_path):
        return ""

    row = conn.execute("SELECT task_id FROM task WHERE task_id=?", (task_id,)).fetchone()
    if row is None:
        shutil.rmtree(task_dir)
        return "ORPHAN_REMOVED"
    try:
        marker.unlink()
    except OSError:
        pass
    return "COMMITTED_MARKER_CLEANED"


def _prepare_task_scaffold(target: Path, task_id: str, title: str, risk: str, flow: str, created_at: str) -> Path:
    """Build a complete V5.2.6 task scaffold in a temporary sibling directory.

    The caller may atomically rename the returned directory after the DB transaction
    has prepared successfully.  No existing task directory is overwritten.
    """
    template_root = Path(__file__).resolve().parent.parent / 'templates' / active_version()
    if not template_root.is_dir():
        raise ValueError(f'template directory not found: {template_root}')
    target = target.resolve()
    if target.exists():
        if any(target.iterdir()) if target.is_dir() else True:
            raise ValueError(f'task scaffold target already exists and is not empty: {target}')
        target.rmdir()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f'.{target.name}.scaffold-{uuid.uuid4().hex[:8]}'
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(template_root, tmp)
    # V5.2.6 Record-first scaffold: create only the durable task shell. Optional
    # business artifacts are created when a role has real content, never because a
    # state machine requires an empty form. Base templates remain available.
    essential = {'task.md', 'acceptance.md', 'status.yaml'}
    for child in list(tmp.iterdir()):
        if child.is_file() and child.name not in essential:
            child.unlink()
    (tmp / 'generated').mkdir(exist_ok=True)
    (tmp / 'evidence' / 'sql').mkdir(parents=True, exist_ok=True)

    replacements = {
        'TASK-YYYYMMDD-XXX': task_id,
        'task_id: ""': f'task_id: "{task_id}"',
    }
    for fp in tmp.iterdir():
        if not fp.is_file() or fp.suffix.lower() not in {'.md', '.yaml', '.yml', '.json'}:
            continue
        try:
            text = fp.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError:
            continue
        for old, new in replacements.items():
            text = text.replace(old, new)
        if fp.name == 'status.yaml':
            text = re.sub(r'(?m)^task_name:\s*.*$', f'task_name: {json.dumps(title or "", ensure_ascii=False)}', text)
            text = re.sub(r'(?m)^created:\s*.*$', f'created: "{created_at[:10]}"', text)
            text = re.sub(r'(?m)^risk_level:\s*.*$', f'risk_level: "{risk}"', text)
            text = re.sub(r'(?m)^flow_level:\s*.*$', f'flow_level: "{flow}"', text)
        fp.write_text(text, encoding='utf-8', newline='\n')
    return tmp

def cmd_task_create(args) -> int:
    task_id = args.id
    if not _TASK_ID_RE.match(task_id):
        print(
            f"ERROR: invalid task id '{task_id}' (must match ^TASK-[A-Za-z0-9][A-Za-z0-9._-]*$)",
            file=sys.stderr,
        )
        return 2
    if args.risk not in _RISK_LEVELS:
        print(f"ERROR: invalid risk level '{args.risk}'", file=sys.stderr)
        return 2
    if args.flow not in _RISK_LEVELS:
        print(f"ERROR: invalid flow level '{args.flow}'", file=sys.stderr)
        return 2
    project_id = args.project
    db_path = dbmod.resolve_db_path(args.db, project_id=project_id)
    if not os.path.isfile(db_path):
        print(
            f"PROJECT_NOT_INITIALIZED: Runtime database not found for project '{project_id}': {db_path}. "
            f"Run 'tp-spec project bootstrap --id {project_id} --root <workspace-root>' (preferred for health checks) "
            "or explicit 'tp-spec project init' before task create.",
            file=sys.stderr,
        )
        return 4
    # Probe existing storage read-only first. A malformed/empty file must not be mutated
    # merely because task create was attempted.
    try:
        probe = dbmod.connect_readonly(db_path)
        try:
            ok, details = dbmod.verify_schema(probe)
            if not ok:
                print(
                    f"PROJECT_NOT_INITIALIZED: Runtime schema is unavailable for project '{project_id}' at {db_path}: "
                    + "; ".join(details)
                    + f". Run 'tp-spec project bootstrap --id {project_id} --root <workspace-root>'.",
                    file=sys.stderr,
                )
                return 4
            proj = probe.execute(
                "SELECT project_id, root_path, base_version FROM project WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        finally:
            probe.close()
    except Exception as exc:
        print(
            f"PROJECT_NOT_INITIALIZED: Runtime database cannot be verified read-only: {db_path}: {exc}. "
            f"Run 'tp-spec project bootstrap --id {project_id} --root <workspace-root>'.",
            file=sys.stderr,
        )
        return 4
    if proj is None:
        print(f"ERROR: project not found: {project_id}", file=sys.stderr)
        return 4

    workspace_root = _task_create_workspace_root(args, project_id)
    if workspace_root is not None:
        stored_root = str(proj["root_path"] or "").strip()
        if not stored_root or not os.path.isabs(stored_root) or not same_path(stored_root, workspace_root):
            print(
                f"PROJECT_WORKSPACE_MISMATCH: Runtime project '{project_id}' is bound to "
                f"{stored_root or '<missing>'}, but this task create targets workspace {workspace_root}; "
                "refusing cross-workspace mutation. Repair the registry/rebind the project before retrying.",
                file=sys.stderr,
            )
            return 4
    try:
        conn = dbmod.connect(db_path)
    except Exception as exc:
        print(f"PROJECT_NOT_INITIALIZED: Runtime database cannot be opened: {db_path}: {exc}", file=sys.stderr)
        return 4
    try:
        try:
            wf = workflow_loader.load_workflow()
        except WorkflowLoadError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 3
        base_version = proj["base_version"] or ""
        # 唯一活动契约门控：缺失版本或非活动版本均拒绝
        if base_version != active_version():
            print(
                f"ERROR: project '{project_id}' base_version={base_version} is not the active contract {active_version()}; task creation rejected",
                file=sys.stderr,
            )
            return 4
        requested_scaffold_target = None
        intake_arg = getattr(args, 'from_intake', None)
        if getattr(args, 'scaffold', False) or intake_arg:
            requested_scaffold_target = (
                Path(args.task_dir).resolve()
                if getattr(args, 'task_dir', None)
                else (Path.cwd() / '.tp-spec' / 'tasks' / task_id).resolve()
            )
            if requested_scaffold_target.exists():
                _recover_interrupted_task_create(
                    conn, requested_scaffold_target, task_id=task_id, project_id=project_id, db_path=db_path
                )

        # 校验 task_id 不存在
        existing = conn.execute("SELECT task_id FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if existing is not None:
            print(f"ERROR: task already exists: {task_id}", file=sys.stderr)
            return 5
        now = dbmod.now_iso()
        scaffold_target = None
        scaffold_tmp = None
        adopted_intake: List[str] = []
        if getattr(args, 'scaffold', False) or intake_arg:
            scaffold_target = requested_scaffold_target
            try:
                scaffold_tmp = _prepare_task_scaffold(scaffold_target, task_id, args.title or '', args.risk, args.flow, now)
                if intake_arg:
                    adopted_intake = _adopt_intake_artifacts(scaffold_tmp, Path(intake_arg), task_id, now)
                _write_task_create_marker(
                    scaffold_tmp,
                    {
                        "schema": _TASK_CREATE_TX_SCHEMA,
                        "task_id": task_id,
                        "project_id": project_id,
                        "db_path": str(Path(db_path).resolve()),
                        "phase": "PREPARED",
                        "created_at": now,
                    },
                )
            except Exception as e:
                if scaffold_tmp is not None and scaffold_tmp.exists():
                    shutil.rmtree(scaffold_tmp, ignore_errors=True)
                print(f"ERROR: scaffold preflight failed: {e}", file=sys.stderr)
                return 6
        try:
            conn.execute('BEGIN')
            conn.execute(
                """
                INSERT INTO task
                  (task_id, project_id, title, risk_level, flow_level,
                   current_state, current_stage, owner_role, owner_agent,
                   priority, base_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'NEW', 'intake', ?, '', NULL, ?, ?, ?)
                """,
                (task_id, project_id, args.title or '', args.risk, args.flow, INITIAL_TASK_OWNER, base_version, now, now),
            )
            cur = conn.execute(
                """
                INSERT INTO task_event
                  (task_id, event_type, from_state, to_state, from_stage, to_stage,
                   actor_role, actor_agent, summary, workflow_version, created_at)
                VALUES (?, 'STATE', NULL, 'NEW', NULL, 'intake', ?, NULL, ?, ?, ?)
                """,
                (task_id, INITIAL_TASK_OWNER, args.summary or '任务创建', wf.version, now),
            )
            event_id = cur.lastrowid
            if scaffold_tmp is not None and scaffold_target is not None:
                # Render authoritative status/events from the still-open DB transaction.
                from . import projection_cmd
                created_task = conn.execute('SELECT * FROM task WHERE task_id=?', (task_id,)).fetchone()
                status_yaml, events_jsonl, _ = projection_cmd.render_projection(conn, created_task)
                (scaffold_tmp / 'status.yaml').write_text(status_yaml, encoding='utf-8', newline='\n')
                (scaffold_tmp / 'events.jsonl').write_text(events_jsonl, encoding='utf-8', newline='\n')
                # A scaffold is runtime-ready immediately: materialize the current
                # generated view in the same create transaction instead of leaving
                # the first role to repair an empty generated/ directory.
                from . import transaction_commit
                create_flush_id = f'CREATE-{uuid.uuid4().hex[:12].upper()}'
                view_rel = transaction_commit._current_view_rel('NEW')
                view_text = transaction_commit._rebuild_current_view_text(
                    scaffold_tmp, created_task, args.summary or '任务创建', create_flush_id
                )
                view_path = scaffold_tmp / view_rel
                view_path.parent.mkdir(parents=True, exist_ok=True)
                view_path.write_text(view_text, encoding='utf-8', newline='\n')
                os.replace(scaffold_tmp, scaffold_target)
                scaffold_tmp = None
                _write_task_create_marker(
                    scaffold_target,
                    {
                        "schema": _TASK_CREATE_TX_SCHEMA,
                        "task_id": task_id,
                        "project_id": project_id,
                        "db_path": str(Path(db_path).resolve()),
                        "phase": "FILES_REPLACED",
                        "created_at": now,
                    },
                )
            conn.execute('COMMIT')
            if scaffold_target is not None:
                try:
                    _task_create_marker_path(scaffold_target).unlink()
                except OSError:
                    pass
        except BaseException:
            try:
                conn.execute('ROLLBACK')
            except Exception:
                pass
            if scaffold_target is not None and scaffold_target.exists():
                shutil.rmtree(scaffold_target, ignore_errors=True)
            if scaffold_tmp is not None and scaffold_tmp.exists():
                shutil.rmtree(scaffold_tmp, ignore_errors=True)
            raise
        message = f"Task created: {task_id} (NEW, event #{event_id})"
        if scaffold_target is not None:
            message += f"; scaffold={scaffold_target}"
        if adopted_intake:
            message += f"; intake_adopted={','.join(adopted_intake)}; intake_source_preserved=true"
        print(message)
        return 0
    finally:
        conn.close()


def cmd_task_transition(args) -> int:
    """V5.2.6 Hardening：禁用活动任务的独立状态推进（任务书 §4.2 方案 A）。

    V5.2.6 遗留的独立 transition（直接 UPDATE task + INSERT STATE 事件）可绕过
    commit 的 durable journal、projection 原子提交、架构评审与验收门禁，已被移除。

    V5.2.6 活动任务：
    - 日常事实入口为 ``task checkpoint/block/resume/verify/complete``；这些命令复用
      durable journal + projection 原子提交，但不暴露旧 handoff/phase gate；
    - 旧 long-state commit 已迁入 migration/history-only；日常只使用 Record-first API；
    - 本命令对活动任务返回非零退出码 ``DIRECT_TRANSITION_DISABLED``；
    - 历史任务（base_version != active_version()）仍按静态归档只读拒绝。

    管理员修复模式请使用 ``tp-spec event sync --admin-recovery``（显式标志 +
    共享 validator + 显式确认文本 + AUDIT 事件），不可用本命令推进状态。
    """
    task_id = args.task
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4
        # 历史任务：静态归档，只读拒绝（不推进、不改写）。
        if (task["base_version"] or "") != active_version():
            print(f"ERROR: legacy contract task is a frozen static archive; the V5.2.6 runtime operates only base_version={active_version()}", file=sys.stderr)
            return 3
        # 活动任务：独立状态推进被禁用（方案 A）。
        print("DIRECT_TRANSITION_DISABLED: V5.2.6 uses record-first task checkpoint/block/resume/complete; direct transition is not a daily API", file=sys.stderr)
        return 9
    finally:
        conn.close()


def cmd_task_get(args) -> int:
    task_id = args.task
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4
        from . import event_policies
        retirement = event_policies.load_task_retirement(conn, task_id)
        retirement_data = retirement.detail if retirement is not None else None
        if args.json:
            data = {k: task[k] for k in task.keys()}
            data["retired"] = retirement is not None
            data["retirement"] = retirement_data
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(f"task_id:         {task['task_id']}")
            print(f"project_id:      {task['project_id']}")
            print(f"title:           {task['title']}")
            print(f"risk_level:      {task['risk_level']}")
            print(f"flow_level:      {task['flow_level']}")
            print(f"current_state:   {task['current_state']}")
            print(f"current_stage:   {task['current_stage']}")
            print(f"owner_role:      {task['owner_role']}")
            print(f"owner_agent:     {task['owner_agent']}")
            print(f"base_version:    {task['base_version']}")
            print(f"created_at:      {task['created_at']}")
            print(f"updated_at:      {task['updated_at']}")
            print(f"completed_at:    {task['completed_at']}")
            print(f"retired:         {str(retirement is not None).lower()}")
            if retirement_data is not None:
                print(f"retire_reason:   {retirement_data.get('reason') or ''}")
                if retirement_data.get('superseded_by'):
                    print(f"superseded_by:   {retirement_data.get('superseded_by')}")
            events = conn.execute(
                "SELECT * FROM task_event WHERE task_id = ? ORDER BY id DESC LIMIT 5",
                (task_id,),
            ).fetchall()
            print(f"\nrecent events ({len(events)}):")
            for ev in reversed(events):
                print(
                    f"  #{ev['id']} [{ev['created_at']}] {ev['event_type']}: "
                    f"{ev['from_state'] or '-'} -> {ev['to_state'] or '-'} | {ev['summary'] or ''}"
                )
        return 0
    finally:
        conn.close()


def cmd_task_list(args) -> int:
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None))
    conn = dbmod.connect(db_path)
    try:
        sql = (
            "SELECT task_id, project_id, title, risk_level, flow_level, "
            "current_state, owner_role FROM task WHERE 1=1"
        )
        params = []
        if args.project:
            sql += " AND project_id = ?"
            params.append(args.project)
        if args.state:
            sql += " AND current_state = ?"
            params.append(args.state)
        if args.risk:
            sql += " AND risk_level = ?"
            params.append(args.risk)
        sql += " ORDER BY created_at DESC"
        rows = conn.execute(sql, params).fetchall()
        if getattr(args, "active", False):
            from . import event_policies
            rows = [r for r in rows if r["current_state"] not in {"COMPLETED", "CANCELLED"} and not event_policies.is_task_retired(conn, r["task_id"])]
        if not rows:
            print("(no tasks)")
            return 0
        headers = ["task_id", "project_id", "title", "risk", "flow", "state", "owner"]
        table_rows = [
            [
                r["task_id"],
                r["project_id"],
                r["title"] or "",
                r["risk_level"],
                r["flow_level"],
                r["current_state"],
                r["owner_role"],
            ]
            for r in rows
        ]
        widths = [len(h) for h in headers]
        for r in table_rows:
            for i, v in enumerate(r):
                widths[i] = max(widths[i], len(v))

        def fmt_row(cells):
            return "  ".join(c.ljust(widths[i]) for i, c in enumerate(cells))

        print(fmt_row(headers))
        print("  ".join("-" * w for w in widths))
        for r in table_rows:
            print(fmt_row(r))
        return 0
    finally:
        conn.close()


def cmd_task_validate(args) -> int:
    task_id = args.task
    db_path = dbmod.resolve_db_path(args.db, project_id=getattr(args, "project", None), task_id=task_id)
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {task_id}", file=sys.stderr)
            return 4
        from . import event_policies
        retirement = event_policies.load_task_retirement(conn, task_id)
        if retirement is not None:
            print(
                f"Task validate OK: {task_id} (retired historical archive; "
                f"last_state={task['current_state']}, base_version={task['base_version']})"
            )
            return 0
        try:
            wf = workflow_loader.load_workflow()
        except WorkflowLoadError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 3
        if (task["base_version"] or "") != active_version():
            print(f"ERROR: legacy contract task is a frozen static archive; the V5.2.6 runtime validates only base_version={active_version()}", file=sys.stderr)
            return 3
        errors = []
        # V5.2.6 Record-first validation protects ledger truth, not process completeness.
        quick = conn.execute("PRAGMA quick_check").fetchone()
        if quick is None or str(quick[0]).lower() != "ok":
            errors.append(f"sqlite integrity check failed: {quick[0] if quick else 'no result'}")
        # STATE history remains immutable/auditable; compatibility transitions stay parseable.
        state_events = conn.execute(
            "SELECT * FROM task_event WHERE task_id = ? AND event_type = 'STATE' ORDER BY id",
            (task_id,),
        ).fetchall()
        visited_states: set = set()
        if not state_events:
            errors.append("no STATE events found")
        else:
            prev_to = None
            for ev in state_events:
                if ev["to_state"]:
                    visited_states.add(ev["to_state"])
                if prev_to is not None:
                    if not wf.is_valid_transition(prev_to, ev["to_state"]):
                        errors.append(
                            f"invalid transition in history: {prev_to} -> {ev['to_state']}"
                        )
                prev_to = ev["to_state"]
            # task.current_state 等于最后一条 STATE 事件的 to_state
            last_state = state_events[-1]["to_state"]
            if last_state != task["current_state"]:
                errors.append(
                    f"current_state mismatch: task={task['current_state']}, "
                    f"last STATE event={last_state}"
                )
            # task.owner_role 等于最后一条 STATE 事件后预期的 owner
            expected_owner = wf.get_state_owner(task["current_state"])
            if expected_owner and task["owner_role"] and task["owner_role"] != expected_owner:
                errors.append(
                    f"owner_role mismatch: task={task['owner_role']}, "
                    f"expected={expected_owner} for state {task['current_state']}"
                )
        # Acceptance completeness is not a workflow gate, but explicit PASS/defer/waive
        # claims must remain evidence/ledger-backed facts.
        task_dir_arg = getattr(args, "task_dir", None)
        if task_dir_arg:
            from .record_first import acceptance_truth_issues
            for issue in acceptance_truth_issues(conn, task_id, Path(task_dir_arg).resolve()):
                errors.append("acceptance truth: " + issue)

        # Public Record-first phases are query facts. Missing optional artifacts, handoff
        # metadata, architecture review or knowledge convergence are never validation errors.
        public_states = {"NEW", "ACTIVE", "BLOCKED", "COMPLETED", "CANCELLED"}
        if str(task["current_state"] or "") in public_states:
            phase = str(task["current_stage"] or "")
            from .record_first import PHASES
            if phase not in PHASES:
                errors.append(f"invalid current_phase: {phase!r}")
        if errors:
            print(f"Task validate FAIL: {task_id}", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 6
        print(
            f"Task validate OK: {task_id} "
            f"(state={task['current_state']}, owner={task['owner_role']})"
        )
        return 0
    finally:
        conn.close()




def cmd_task_retire(args) -> int:
    """Administratively retire a non-terminal historical task without forging a terminal state.

    Retirement is DB-ledger only by design: the workflow's last real state is preserved,
    while release/upgrade active-task scans ignore the instance.  This is appropriate for
    orphaned/superseded tasks whose task directory may no longer exist.
    """
    if args.actor != "human_owner":
        print("ERROR: task retire requires --actor human_owner", file=sys.stderr)
        return 2
    db_path = dbmod.resolve_db_path(args.db, task_id=args.task)
    if not os.path.isfile(db_path):
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        return 4
    from . import event_policies
    conn = dbmod.connect(db_path)
    try:
        task = conn.execute("SELECT * FROM task WHERE task_id=?", (args.task,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {args.task}", file=sys.stderr)
            return 4
        if (task["current_state"] or "") in {"COMPLETED", "CANCELLED"}:
            print("ERROR: terminal tasks are already inactive and cannot be retired", file=sys.stderr)
            return 5
        existing = event_policies.load_task_retirement(conn, args.task)
        if existing is not None:
            detail = existing.detail
            same = (str(detail.get("reason") or "") == args.reason and
                    str(detail.get("superseded_by") or "") == str(args.superseded_by or ""))
            if same:
                print(f"task retire: already retired ({args.task}); no changes")
                return 0
            print("ERROR: task is already retired with different metadata; retirement is append-only", file=sys.stderr)
            return 6
        superseded_by = str(args.superseded_by or "")
        if superseded_by:
            replacement = conn.execute("SELECT * FROM task WHERE task_id=?", (superseded_by,)).fetchone()
            if replacement is None:
                print(f"ERROR: superseding task not found: {superseded_by}", file=sys.stderr)
                return 6
            if replacement["project_id"] != task["project_id"]:
                print("ERROR: superseding task must belong to the same project", file=sys.stderr)
                return 6
            if superseded_by == args.task:
                print("ERROR: a task cannot supersede itself", file=sys.stderr)
                return 6
        now = dbmod.now_iso()
        tx_id = f"RETIRE-{uuid.uuid4().hex}"
        detail = {
            "transaction_id": tx_id,
            "producer": "task_retire",
            "schema_version": active_version(),
            "task_id": args.task,
            "actor_role": args.actor,
            "created_at": now,
            "reason": args.reason,
            "superseded_by": superseded_by,
            "last_state": task["current_state"] or "",
            "base_version": task["base_version"] or "",
        }
        conn.execute("BEGIN")
        try:
            conn.execute(
                "INSERT INTO task_event (task_id,event_type,actor_role,reason_code,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (args.task, "TASK_RETIRED", args.actor, "SUPERSEDED" if superseded_by else "HISTORICAL_RETIRE",
                 args.reason, json.dumps(detail, ensure_ascii=False), active_version(), now),
            )
            conn.execute("UPDATE task SET updated_at=? WHERE task_id=?", (now, args.task))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        suffix = f"; superseded_by={superseded_by}" if superseded_by else ""
        print(f"task retire: {args.task}; last_state={task['current_state']}; reason={args.reason}{suffix}")
        return 0
    finally:
        conn.close()


def _replace_artifact_contract_version(text: str, target: str) -> str:
    """Update an existing artifact_contract.version declaration without rewriting prose."""
    pattern = re.compile(r'(?ms)(^artifact_contract:\s*\n\s+version:\s*["\']?)([^"\'\n#]+)(["\']?\s*(?:#.*)?$)')
    return pattern.sub(lambda m: m.group(1) + target + m.group(3), text, count=1)


def _upgrade_contract_artifact_text(name: str, text: str, source: str, target: str) -> str:
    """Apply deterministic artifact-shape migrations while preserving business prose."""
    out = _replace_artifact_contract_version(text, target)
    if name == "task.md":
        # task.md carries a human-readable contract declaration rather than a
        # front-matter artifact_contract block. Upgrade only the exact contract/template
        # references, never arbitrary prose mentioning historical versions.
        out = out.replace(f"artifact_contract.version: {source}", f"artifact_contract.version: {target}")
        out = out.replace(f"templates/{source}", f"templates/{target}")
    if name == "codex-review.md":
        # V5.2.6 review routing is Runtime-owned and unambiguously named next_state.
        out = re.sub(r"(?m)^(\s*)intended_next\s*:\s*(.*)$", r"\1next_state: \2", out, count=1)
    if name == "acceptance.md" and "owner_waivers:" not in out:
        marker = "## 数据库验证声明"
        block = (
            "## Owner 跳过记录\n\n"
            "```yaml\n"
            "owner_waivers: []\n"
            "```\n\n"
        )
        if marker in out:
            out = out.replace(marker, block + marker, 1)
        else:
            out = out.rstrip() + "\n\n" + block
    return out


def _task_migratable_artifacts(task_dir: Path) -> Dict[str, str]:
    """Return task-root text artifacts eligible for deterministic shape migration.

    Some older/current artifacts (notably codex-review.md, acceptance.md and task.md)
    intentionally do not carry an explicit artifact_contract front-matter block, but their
    schema still evolves. Migration therefore cannot limit itself to files exposing a
    version field.
    """
    allowed = {
        "task.md", "acceptance.md", "codex-review.md", "implementation.md",
        "quality-and-knowledge.md", "architecture-review.md",
        "requirement-knowledge.md", "requirement-clarifications.md",
        "requirement-decisions.md", "requirement-test-guide.md",
    }
    result: Dict[str, str] = {}
    names = allowed | set(_task_contract_files(task_dir))
    for name in sorted(names):
        path = task_dir / name
        if path.is_file():
            try:
                result[name] = path.read_text(encoding="utf-8-sig")
            except OSError:
                continue
    return result


def _task_contract_files(task_dir: Path) -> Dict[str, str]:
    """Return root task artifacts that explicitly declare artifact_contract.version."""
    result: Dict[str, str] = {}
    for path in sorted(task_dir.iterdir() if task_dir.is_dir() else []):
        if not path.is_file() or path.suffix.lower() not in {'.md', '.yaml', '.yml'}:
            continue
        try:
            text = path.read_text(encoding='utf-8-sig')
        except OSError:
            continue
        if re.search(r'(?ms)^artifact_contract:\s*\n\s+version:', text):
            result[path.name] = text
    return result


def _migration_grandfathered_gates(conn, task_id: str) -> List[str]:
    """Describe gates already crossed under the source contract.

    Contract migration is non-retroactive: a new release may govern future state
    changes, but it must never require a historical event that did not exist when a
    task legally crossed that boundary.
    """
    rows = conn.execute(
        "SELECT to_state FROM task_event WHERE task_id=? AND event_type='STATE' ORDER BY id",
        (task_id,),
    ).fetchall()
    visited = {str(r["to_state"] or "") for r in rows}
    gates: List[str] = []
    if visited & {"DEVELOPING", "ASSISTING", "VERIFYING", "BROWSER_VERIFYING", "REVIEWING", "CLOSING", "COMPLETED"}:
        gates.append("pre_DEVELOPING_gates")
    if visited & {"VERIFYING", "BROWSER_VERIFYING", "REVIEWING", "CLOSING", "COMPLETED"}:
        gates.append("pre_VERIFYING_gates")
    if visited & {"CLOSING", "COMPLETED"}:
        gates.append("pre_CLOSING_gates")
    return gates


def _deep_projection_snapshot(conn, task, task_dir: Path, actor: str = "human_owner") -> Dict[str, List[str]]:
    """Read-only canonical comparison usable before/after contract migration.

    Unlike the legacy projection validator, events are compared against the full
    canonical DB rendering, not merely line count/latest state. Handoff is compared
    against the latest HANDOFF event payload and generated view digests are checked.
    """
    from . import projection_cmd, reconcile_cmd

    issues: Dict[str, List[str]] = {"status": [], "events": [], "handoff": [], "generated": []}
    # events.jsonl can be rendered independently of task.base_version.
    rows = conn.execute("SELECT * FROM task_event WHERE task_id=? ORDER BY id", (task["task_id"],)).fetchall()
    expected_events, _ = projection_cmd._build_events_jsonl(rows, task["task_id"])
    ep = task_dir / "events.jsonl"
    if not ep.is_file():
        issues["events"].append("events.jsonl missing")
    elif ep.read_bytes() != expected_events.encode("utf-8"):
        issues["events"].append("events.jsonl differs from canonical DB projection")

    expected_handoff, _ = reconcile_cmd._handoff_texts(conn, task, task_dir, actor)
    hp = task_dir / "handoff.json"
    if expected_handoff is not None:
        if not hp.is_file():
            issues["handoff"].append("handoff.json missing")
        else:
            try:
                actual = hp.read_text(encoding="utf-8-sig")
            except OSError as exc:
                issues["handoff"].append(f"handoff.json unreadable: {exc}")
            else:
                if not reconcile_cmd._handoff_matches(actual, expected_handoff):
                    issues["handoff"].append("handoff.json differs from canonical HANDOFF event")

    issues["generated"].extend(reconcile_cmd._check_generated_digest(task_dir, task))

    # Full status byte comparison is available once the DB is on the active contract.
    sp = task_dir / "status.yaml"
    if str(task["base_version"] or "") == active_version():
        try:
            expected_status, _, _ = projection_cmd.render_projection(conn, task)
        except Exception as exc:  # noqa: BLE001
            issues["status"].append(f"status render failed: {type(exc).__name__}: {exc}")
        else:
            if not sp.is_file():
                issues["status"].append("status.yaml missing")
            elif sp.read_bytes() != expected_status.encode("utf-8"):
                issues["status"].append("status.yaml differs from canonical DB projection")
    elif sp.is_file():
        try:
            st = sp.read_text(encoding="utf-8-sig")
            state = _yaml_scalar(st, "current_state") or ""
            if state != str(task["current_state"] or ""):
                issues["status"].append(
                    f"status current_state mismatch: file={state!r}, db={task['current_state']!r}"
                )
        except OSError as exc:
            issues["status"].append(f"status.yaml unreadable: {exc}")
    return issues


def cmd_task_migrate(args) -> int:
    """Atomically migrate/repair a non-terminal task to the active contract.

    The operation is non-retroactive, journal-backed and idempotent.  It treats the
    SQLite ledger as canonical for events/handoff and rebuilds all runtime projections
    instead of editing existing JSONL/handoff content in place.
    """
    target = args.to or active_version()
    if target != active_version():
        print(f"ERROR: task migrate currently supports only active contract {active_version()}", file=sys.stderr)
        return 2
    task_dir = Path(args.task_dir).resolve()
    if not task_dir.is_dir():
        print(f"ERROR: task-dir not found: {task_dir}", file=sys.stderr)
        return 4
    status_path = task_dir / "status.yaml"
    if not status_path.is_file():
        print("ERROR: task migrate requires status.yaml", file=sys.stderr)
        return 4
    status_text = status_path.read_text(encoding="utf-8-sig")
    status_task = _yaml_scalar(status_text, "task_id") or ""
    if status_task and status_task != args.task:
        print(f"ERROR: task-dir belongs to {status_task}, not {args.task}", file=sys.stderr)
        return 4

    db_path = dbmod.resolve_db_path(args.db, task_id=args.task)
    if not os.path.isfile(db_path):
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        return 4
    conn = dbmod.connect(db_path)
    try:
        from . import transaction_commit, projection_cmd, reconcile_cmd, event_policies
        from .migrations.v5_2_3.role_map import map_active_owner
        task = conn.execute("SELECT * FROM task WHERE task_id=?", (args.task,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {args.task}", file=sys.stderr)
            return 4
        if event_policies.is_task_retired(conn, args.task):
            print("ERROR: retired historical tasks are immutable archives and are not migrated", file=sys.stderr)
            return 5
        if (task["current_state"] or "") in {"COMPLETED", "CANCELLED"}:
            print("ERROR: terminal tasks are immutable archives and are not migrated", file=sys.stderr)
            return 5
        old = str(task["base_version"] or "")
        if not old:
            print("ERROR: DB task.base_version is empty; migration source is ambiguous", file=sys.stderr)
            return 6
        project = conn.execute("SELECT base_version FROM project WHERE project_id=?", (task["project_id"],)).fetchone()
        if project is not None and str(project["base_version"] or "") != target:
            print(
                f"ERROR: project base_version={project['base_version']!r} is not {target}; "
                "run official 'tp-spec project upgrade-contract --id <PROJECT>' first, then migrate in-flight tasks",
                file=sys.stderr,
            )
            return 6

        contract_files = _task_contract_files(task_dir)
        migratable_artifacts = _task_migratable_artifacts(task_dir)
        versions = _artifact_contract_versions(task_dir)
        status_base = _yaml_scalar(status_text, "base_version") or ""
        m_contract = re.search(r'(?ms)^artifact_contract:\s*\n\s+version:\s*["\']?([^"\'\n#]+)', status_text)
        status_contract = m_contract.group(1).strip() if m_contract else ""
        before_drift = _deep_projection_snapshot(conn, task, task_dir, args.actor)
        all_contracts_current = bool(versions) and all(v == target for v in versions.values())
        no_drift = not any(before_drift.values())
        if old == target and status_base == target and status_contract == target and all_contracts_current and no_drift:
            print(f"task migrate: already current ({args.task} -> {target}); no changes")
            return 0

        operation_kind = "CONTRACT_MIGRATION" if old != target else "CURRENT_CONTRACT_REPAIR"
        from . import risk_signals
        risk_scan = risk_signals.scan_task_artifacts(task_dir)
        risk_order = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
        old_risk = str(task["risk_level"] or "L1")
        floor = str(risk_scan.get("floor") or "")
        migrated_risk = floor if risk_order.get(floor, -1) > risk_order.get(old_risk, -1) else old_risk
        texts: Dict[str, str] = {}
        for name, text in migratable_artifacts.items():
            texts[name] = _upgrade_contract_artifact_text(name, text, old, target)

        current = str(task["current_state"] or "")
        owner = str(task["owner_role"] or "")
        migrated_owner = map_active_owner(owner) or "tp-software-lifecycle"
        legacy_phase_map = {
            "NEW": "intake", "RISK_ANALYZING": "requirement",
            "REQUIREMENT_CLARIFYING": "requirement", "PRODUCT_DESIGNING": "product",
            "PRODUCT_CONFIRMING": "product", "TECHNICAL_DISCOVERY": "discovery",
            "TECH_DESIGNING": "architecture", "DISCOVERY_REVIEW_REQUIRED": "architecture",
            "CHANGE_CONFIRMING": "requirement", "DEVELOPING": "development",
            "ASSISTING": "development", "VERIFYING": "verification",
            "BROWSER_VERIFYING": "verification", "REVIEWING": "review",
            "CLOSING": "delivery", "BLOCKED": str(task["current_stage"] or "other").lower(),
        }
        migrated_phase = legacy_phase_map.get(current, str(task["current_stage"] or "other").lower())
        if migrated_phase not in {"intake","requirement","product","architecture","planning","discovery","development","verification","review","delivery","other"}:
            migrated_phase = "other"
        # Human-confirmation legacy states are genuine blockers; other legacy workflow
        # microstates collapse to ACTIVE. NEW remains NEW until first checkpoint.
        if current == "NEW":
            migrated_state = "NEW"
        elif current in {"BLOCKED", "PRODUCT_CONFIRMING", "CHANGE_CONFIRMING"}:
            migrated_state = "BLOCKED"
        else:
            migrated_state = "ACTIVE"
        timestamp = dbmod.now_iso()
        flush_id = f"MIGRATE-{uuid.uuid4().hex}"
        view_rel = transaction_commit._current_view_rel(migrated_state)
        grandfathered = _migration_grandfathered_gates(conn, args.task) if old != target else []

        def db_and_render(tx_conn, transaction_id=""):
            detail = {
                "kind": operation_kind,
                "from_version": old,
                "to_version": target,
                "flush_id": flush_id,
                "transaction_id": transaction_id,
                "producer": "task_migrate",
                "schema_version": target,
                "task_id": args.task,
                "actor_role": args.actor,
                "created_at": timestamp,
                "migration_policy": "non_retroactive",
                "grandfathered_gates": grandfathered,
                "future_transitions_use_target_contract": True,
                "before_artifact_versions": versions,
                "before_projection_drift": before_drift,
            }
            if migrated_risk != old_risk:
                detail["risk_escalation"] = {
                    "from": old_risk, "to": migrated_risk,
                    "signals": list(risk_scan.get("signals") or []),
                }
            detail["legacy_state"] = current
            detail["record_first_state"] = migrated_state
            detail["record_first_phase"] = migrated_phase
            detail["owner_role_migration"] = {"from": owner, "to": migrated_owner}
            tx_conn.execute(
                "UPDATE task SET base_version=?, risk_level=?, current_state=?, current_stage=?, owner_role=?, updated_at=? WHERE task_id=?",
                (target, migrated_risk, migrated_state, migrated_phase, migrated_owner, timestamp, args.task),
            )
            tx_conn.execute(
                "INSERT INTO task_event (task_id,event_type,actor_role,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?)",
                (args.task, "RECONCILIATION", args.actor,
                 f"{operation_kind.lower()} {old} -> {target}; {current} -> {migrated_state}/{migrated_phase}",
                 json.dumps(detail, ensure_ascii=False), target, timestamp),
            )
            if current != migrated_state:
                tx_conn.execute(
                    "INSERT INTO task_event (task_id,event_type,from_state,to_state,from_stage,to_stage,actor_role,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (args.task, "STATE", current, migrated_state, task["current_stage"], migrated_phase,
                     args.actor, "V5.2.6 record-first state collapse", json.dumps(detail, ensure_ascii=False), target, timestamp),
                )
            refreshed = tx_conn.execute("SELECT * FROM task WHERE task_id=?", (args.task,)).fetchone()
            status_yaml, events_jsonl, warnings = projection_cmd.render_projection(tx_conn, refreshed)
            for warning in warnings:
                print(f"WARN: {warning}", file=sys.stderr)
            final_texts = dict(texts)
            final_texts["status.yaml"] = status_yaml
            final_texts["events.jsonl"] = events_jsonl
            _expected, rebuild = reconcile_cmd._handoff_texts(tx_conn, refreshed, task_dir, args.actor)
            if rebuild is not None:
                final_texts["handoff.json"] = rebuild
            else:
                template = Path(__file__).resolve().parent.parent / "templates" / active_version() / "handoff.json"
                final_texts["handoff.json"] = template.read_text(encoding="utf-8")
            return transaction_commit._finalize_texts(
                task_dir,
                final_texts,
                view_rel,
                lambda: transaction_commit._rebuild_current_view_text(
                    task_dir, refreshed,
                    f"contract {'migrated' if old != target else 'repaired'} {old} -> {target}",
                    flush_id,
                ),
            )

        rel_paths = sorted(set(texts) | {"status.yaml", "events.jsonl", "handoff.json", view_rel})
        transaction_commit._commit_with_recovery(
            task_dir, conn, rel_paths, db_and_render,
            task_id=args.task, operation="contract_migrate",
            db_state_before=current, target_state=migrated_state,
            owner_before=owner, owner_after=migrated_owner, flush_id=flush_id,
        )
        refreshed = conn.execute("SELECT * FROM task WHERE task_id=?", (args.task,)).fetchone()
        after_drift = _deep_projection_snapshot(conn, refreshed, task_dir, args.actor)
        if any(after_drift.values()):
            print(
                "ERROR: migration committed but self-check found projection drift; run reconcile: " +
                json.dumps(after_drift, ensure_ascii=False),
                file=sys.stderr,
            )
            return 7
        contract_issues = _post_migration_contract_issues(task_dir, target)
        if contract_issues:
            print(
                "ERROR: migration committed but explicit artifact contracts remain stale: " + ", ".join(contract_issues),
                file=sys.stderr,
            )
            return 7
        print(
            f"task migrate: {args.task} {old} -> {target}; kind={operation_kind}; "
            f"state={migrated_state}; phase={migrated_phase}; owner={migrated_owner}; "
            f"grandfathered={','.join(grandfathered) or 'none'}; flush_id={flush_id}"
        )
        return 0
    finally:
        conn.close()


def _artifact_contract_versions(task_dir: Path) -> Dict[str, str]:
    """Return explicit artifact_contract.version values for root task artifacts."""
    out: Dict[str, str] = {}
    for name, text in _task_contract_files(task_dir).items():
        m = re.search(r'(?ms)^artifact_contract:\s*\n\s+version:\s*["\']?([^"\'\n#]+)', text)
        if m:
            out[name] = m.group(1).strip()
    return out


def _post_migration_contract_issues(task_dir: Path, target: str) -> List[str]:
    """Return any explicit root artifact contract still not on the target version."""
    return [
        f"{name}:{version}"
        for name, version in sorted(_artifact_contract_versions(task_dir).items())
        if version != target
    ]


def cmd_task_migration_plan(args) -> int:
    """Read-only upgrade gate with deep canonical projection comparison."""
    db_path = dbmod.resolve_db_path(args.db, project_id=args.project)
    if not os.path.isfile(db_path):
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        return 4
    conn = dbmod.connect(db_path)
    try:
        from . import event_policies
        project = conn.execute("SELECT * FROM project WHERE project_id=?", (args.project,)).fetchone()
        if project is None:
            print(f"ERROR: project not found: {args.project}", file=sys.stderr)
            return 4
        tasks_root = Path(args.tasks_root).resolve() if args.tasks_root else (Path(project["root_path"]) / ".tp-spec" / "tasks").resolve()
        rows = conn.execute(
            "SELECT * FROM task WHERE project_id=? AND current_state NOT IN ('COMPLETED','CANCELLED') ORDER BY created_at, task_id",
            (args.project,),
        ).fetchall()

        retired_ids: List[str] = []
        active_rows = []
        for task in rows:
            if event_policies.is_task_retired(conn, task["task_id"]):
                retired_ids.append(str(task["task_id"]))
            else:
                active_rows.append(task)

        items: List[Dict[str, Any]] = []
        for task in active_rows:
            task_id = str(task["task_id"])
            task_dir = tasks_root / task_id
            db_base = str(task["base_version"] or "")
            entry: Dict[str, Any] = {
                "task_id": task_id,
                "state": str(task["current_state"] or ""),
                "task_dir": str(task_dir),
                "four_way": {},
                "classification": "",
                "decision_options": [],
                "issues": [],
            }
            if not task_dir.is_dir():
                entry["four_way"] = {
                    "artifact_contract": "missing-task-dir",
                    "sqlite_task_base_version": db_base,
                    "event_ledger": "unavailable",
                    "handoff_projection": "unavailable",
                    "generated_projection": "unavailable",
                }
                entry["classification"] = "TASK_DIR_MISSING"
                entry["decision_options"] = ["RETIRE_HISTORICAL", "WAIT_FOR_CONFIRMATION"]
                entry["issues"].append(f"task directory missing: {task_dir}")
                items.append(entry)
                continue

            status_path = task_dir / "status.yaml"
            status_base = ""
            status_contract = ""
            status_state = ""
            if status_path.is_file():
                status_text = status_path.read_text(encoding="utf-8-sig")
                status_base = _yaml_scalar(status_text, "base_version") or ""
                status_state = _yaml_scalar(status_text, "current_state") or ""
                m = re.search(r'(?ms)^artifact_contract:\s*\n\s+version:\s*["\']?([^"\'\n#]+)', status_text)
                status_contract = m.group(1).strip() if m else ""
            versions = _artifact_contract_versions(task_dir)
            unique_versions = sorted(set(versions.values()))
            file_contract = unique_versions[0] if len(unique_versions) == 1 else ("MIXED:" + ",".join(unique_versions) if unique_versions else "MISSING")

            deep = _deep_projection_snapshot(conn, task, task_dir, "human_owner")
            event_status = "ok" if not deep["events"] else "drift"
            handoff_status = "ok" if not deep["handoff"] else "drift"
            generated_status = "ok" if not deep["generated"] else "drift"
            status_status = "ok" if not deep["status"] else "drift"
            entry["four_way"] = {
                "artifact_contract": file_contract,
                "status_base_version": status_base or "MISSING",
                "status_artifact_contract": status_contract or "MISSING",
                "sqlite_task_base_version": db_base or "MISSING",
                "status_projection": status_status,
                "event_ledger": event_status,
                "handoff_projection": handoff_status,
                "generated_projection": generated_status,
            }
            entry["artifact_versions"] = versions
            for bucket in ("status", "events", "handoff", "generated"):
                entry["issues"].extend(deep[bucket])
            if status_state and status_state != str(task["current_state"] or ""):
                entry["issues"].append(f"DB/status state mismatch: db={task['current_state']!r}, status={status_state!r}")

            files_active = bool(versions) and all(v == active_version() for v in versions.values())
            files_same_db = bool(versions) and all(v == db_base for v in versions.values())
            healthy_views = not any(deep.values()) and (not status_state or status_state == str(task["current_state"] or ""))
            if db_base == active_version() and status_base == active_version() and status_contract == active_version() and files_active and healthy_views:
                entry["classification"] = "CURRENT"
                entry["decision_options"] = ["NO_ACTION"]
            elif db_base and db_base != active_version() and status_base == db_base and status_contract == db_base and files_same_db and healthy_views:
                entry["classification"] = "LEGACY_CONSISTENT"
                entry["decision_options"] = ["KEEP_OLD_ARCHIVE", "MIGRATE_TO_ACTIVE", "WAIT_FOR_CONFIRMATION"]
            else:
                entry["classification"] = "CONTRACT_MISMATCH"
                entry["decision_options"] = ["MIGRATE_TO_ACTIVE", "WAIT_FOR_CONFIRMATION"]
                if db_base != status_base:
                    entry["issues"].append(f"DB/status base_version mismatch: db={db_base!r}, status={status_base!r}")
                if status_contract and status_contract != db_base:
                    entry["issues"].append(f"DB/status artifact contract mismatch: db={db_base!r}, artifact={status_contract!r}")
                if len(unique_versions) > 1:
                    entry["issues"].append(f"mixed artifact contracts: {unique_versions}")
            items.append(entry)

        blocked = [i for i in items if i["classification"] != "CURRENT"]
        project_base = str(project["base_version"] or "")
        project_contract_current = project_base == active_version()
        report = {
            "schema": "tp-spec.task-migration-plan/v3",
            "active_version": active_version(),
            "project_id": args.project,
            "project_base_version": project_base,
            "project_contract_current": project_contract_current,
            "tasks_root": str(tasks_root),
            "non_terminal_db_tasks": len(rows),
            "retired_historical_tasks": retired_ids,
            "active_non_terminal_tasks": len(items),
            "release_gate": "PASS" if (project_contract_current and not blocked) else "BLOCKED",
            "project_action": "NO_ACTION" if project_contract_current else "RUN_PROJECT_UPGRADE_CONTRACT",
            "requires_explicit_decision": [i["task_id"] for i in blocked],
            "tasks": items,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if getattr(args, "gate", False) and (blocked or not project_contract_current):
            return 8
        return 0
    finally:
        conn.close()


def cmd_task_artifact_path(args) -> int:
    """Return/create the canonical task-local destination for auxiliary artifacts."""
    task_dir = Path(args.task_dir).resolve()
    kind = args.kind
    mapping = {
        "verification-sql": task_dir / "evidence" / "sql",
        "test-evidence": task_dir / "evidence",
        "execution-temp": task_dir.parent.parent / ".execution" / task_dir.name / (args.role or "unknown"),
    }
    base = mapping[kind]
    name = (args.name or "").strip()
    if name:
        candidate = Path(name)
        if candidate.name != name or name in {".", ".."}:
            print("ERROR: --name must be a plain file name without path traversal", file=sys.stderr)
            return 2
        target = base / name
    else:
        target = base
    if args.ensure:
        (base if name else target).mkdir(parents=True, exist_ok=True)
    print(str(target))
    return 0


def _acceptance_table_rows(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse acceptance table rows without rewriting unrelated prose."""
    from .yaml_checks import normalize_verdict
    rows: Dict[str, Dict[str, Any]] = {}
    for idx, line in enumerate(text.splitlines()):
        m = re.match(r"^\s*\|\s*(AC-[^|\s]+)\s*\|", line)
        if not m:
            continue
        cells = line.split("|")
        if len(cells) <= 9:
            continue
        rows[m.group(1)] = {
            "index": idx,
            "cells": cells,
            "witness": cells[7].strip().lower(),
            "verdict": normalize_verdict(cells[8]),
        }
    return rows


def _set_acceptance_verdicts(text: str, verdicts: Dict[str, str]) -> str:
    lines = text.splitlines()
    rows = _acceptance_table_rows(text)
    for ac, verdict in verdicts.items():
        row = rows[ac]
        cells = list(row["cells"])
        cells[8] = f" {verdict} "
        lines[row["index"]] = "|".join(cells)
    return "\n".join(lines) + ("\n" if text.endswith(("\n", "\r\n")) else "")


def _upsert_acceptance_yaml_list(text: str, key: str, entries: List[Dict[str, Any]]) -> str:
    """Upsert a dedicated fenced YAML list block in acceptance.md."""
    import yaml
    pattern = re.compile(r"```yaml\s*\n(?P<body>.*?)```", re.DOTALL)
    matches = list(pattern.finditer(text))
    for match in matches:
        try:
            data = yaml.safe_load(match.group("body")) or {}
        except Exception:
            continue
        if isinstance(data, dict) and key in data:
            current = data.get(key)
            if not isinstance(current, list):
                raise ValueError(f"acceptance.md {key} must be a list")
            by_ac = {str(x.get("ac") or ""): x for x in current if isinstance(x, dict)}
            for item in entries:
                by_ac[str(item["ac"])] = item
            data[key] = list(by_ac.values())
            body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).rstrip() + "\n"
            return text[:match.start()] + "```yaml\n" + body + "```" + text[match.end():]
    heading = "\n## Owner acceptance decisions\n\n"
    block = yaml.safe_dump({key: entries}, allow_unicode=True, sort_keys=False).rstrip() + "\n"
    return text.rstrip() + heading + "```yaml\n" + block + "```\n"


def cmd_task_acceptance_override(args) -> int:
    """Record an explicit human_owner defer/waive decision for pending acceptance.

    This is an audited Runtime write, not a manual SQLite/artifact edit. It never
    turns unexecuted tests into PASS: defer => DEFERRED_ACCEPTED, waive => OWNER_WAIVED.
    """
    if args.actor != "human_owner":
        print("ERROR: acceptance-override requires --actor human_owner", file=sys.stderr)
        return 2
    task_dir = Path(args.task_dir).resolve()
    acceptance_path = task_dir / "acceptance.md"
    if not acceptance_path.is_file():
        print("ERROR: acceptance.md not found", file=sys.stderr)
        return 4
    db_path = dbmod.resolve_db_path(args.db, task_id=args.task)
    if not os.path.isfile(db_path):
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        return 4
    text = acceptance_path.read_text(encoding="utf-8-sig")
    rows = _acceptance_table_rows(text)
    conn = dbmod.connect(db_path)
    try:
        from . import transaction_commit, projection_cmd, event_policies
        task = conn.execute("SELECT * FROM task WHERE task_id=?", (args.task,)).fetchone()
        if task is None:
            print(f"ERROR: task not found: {args.task}", file=sys.stderr)
            return 4
        if event_policies.is_task_retired(conn, args.task):
            print("ERROR: retired historical tasks are immutable archives", file=sys.stderr)
            return 5
        state = str(task["current_state"] or "")
        if state not in {"ACTIVE", "VERIFYING", "BROWSER_VERIFYING", "REVIEWING"}:
            print("ERROR: acceptance-override requires ACTIVE work or a legacy verification state", file=sys.stderr)
            return 5

        selected: List[str] = []
        if args.scope == "human-pending":
            selected.extend(ac for ac, row in rows.items() if row["witness"] == "human" and row["verdict"] == "PENDING")
        selected.extend(args.ac or [])
        selected = list(dict.fromkeys(selected))
        if not selected:
            print("ERROR: no acceptance criteria selected", file=sys.stderr)
            return 6
        missing = [ac for ac in selected if ac not in rows]
        if missing:
            print("ERROR: unknown acceptance criteria: " + ", ".join(missing), file=sys.stderr)
            return 6
        illegal = [ac for ac in selected if rows[ac]["verdict"] not in {"PENDING", "BLOCKED", "DEFERRED_ACCEPTED", "OWNER_WAIVED"}]
        if illegal:
            print("ERROR: acceptance-override only applies to pending/blocked/deferred/waived rows: " + ", ".join(illegal), file=sys.stderr)
            return 6
        if args.mode == "defer" and (not args.reverify_owner or not args.trigger):
            print("ERROR: defer requires --reverify-owner and --trigger", file=sys.stderr)
            return 6

        target_verdict = "DEFERRED_ACCEPTED" if args.mode == "defer" else "OWNER_WAIVED"
        timestamp = dbmod.now_iso()
        verdicts = {ac: target_verdict for ac in selected}
        updated = _set_acceptance_verdicts(text, verdicts)
        if args.mode == "defer":
            entries = [{
                "ac": ac,
                "recorded_at": timestamp,
                "reason": args.reason,
                "residual_risk": args.residual_risk,
                "reverify_owner": args.reverify_owner,
                "trigger": args.trigger,
            } for ac in selected]
            updated = _upsert_acceptance_yaml_list(updated, "deferred_acceptance", entries)
        else:
            entries = [{
                "ac": ac,
                "recorded_at": timestamp,
                "reason": args.reason,
                "residual_risk": args.residual_risk,
                "actor": "human_owner",
            } for ac in selected]
            updated = _upsert_acceptance_yaml_list(updated, "owner_waivers", entries)

        # Validate the candidate artifact before any durable write.
        from .yaml_checks import check_acceptance_yaml
        candidate = check_acceptance_yaml(updated, enforce_completion=False)
        if not candidate.ok:
            print("ERROR: acceptance override would create invalid acceptance.md: " + "; ".join(candidate.issues), file=sys.stderr)
            return 7

        flush_id = f"OWNER-ACCEPT-{uuid.uuid4().hex}"
        view_rel = transaction_commit._current_view_rel(state)
        owner = str(task["owner_role"] or "")

        def db_and_render(tx_conn, transaction_id=""):
            detail = {
                "transaction_id": transaction_id,
                "producer": "task_acceptance_override",
                "schema_version": active_version(),
                "task_id": args.task,
                "actor_role": "human_owner",
                "created_at": timestamp,
                "flush_id": flush_id,
                "mode": args.mode,
                "acs": selected,
                "reason": args.reason,
                "residual_risk": args.residual_risk,
                "reverify_owner": args.reverify_owner or "",
                "trigger": args.trigger or "",
            }
            tx_conn.execute(
                "INSERT INTO task_event (task_id,event_type,actor_role,reason_code,summary,detail_json,workflow_version,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (args.task, "OWNER_ACCEPTANCE_DECISION", "human_owner", args.mode.upper(),
                 f"human_owner acceptance {args.mode}: {', '.join(selected)}",
                 json.dumps(detail, ensure_ascii=False), active_version(), timestamp),
            )
            tx_conn.execute("UPDATE task SET updated_at=? WHERE task_id=?", (timestamp, args.task))
            refreshed = tx_conn.execute("SELECT * FROM task WHERE task_id=?", (args.task,)).fetchone()
            status_yaml, events_jsonl, warnings = projection_cmd.render_projection(tx_conn, refreshed)
            for warning in warnings:
                print(f"WARN: {warning}", file=sys.stderr)
            return transaction_commit._finalize_texts(
                task_dir,
                {"acceptance.md": updated, "status.yaml": status_yaml, "events.jsonl": events_jsonl},
                view_rel,
                lambda: transaction_commit._rebuild_current_view_text(
                    task_dir, refreshed, f"human_owner acceptance {args.mode}: {', '.join(selected)}", flush_id
                ),
            )

        transaction_commit._commit_with_recovery(
            task_dir, conn, ["acceptance.md", "status.yaml", "events.jsonl", view_rel], db_and_render,
            task_id=args.task, operation="owner_acceptance_override",
            db_state_before=state, target_state=state,
            owner_before=owner, owner_after=owner, flush_id=flush_id,
        )
        print(f"acceptance-override: mode={args.mode}; acs={','.join(selected)}; state={state}; flush_id={flush_id}")
        return 0
    finally:
        conn.close()


def _parse_knowledge_signal_args(values):
    result = []
    for raw in values or []:
        try:
            item = json.loads(raw)
        except Exception as exc:
            raise ValueError(f"invalid --knowledge-signal-json: {exc}") from exc
        if not isinstance(item, dict):
            raise ValueError("--knowledge-signal-json must decode to an object")
        result.append(item)
    return result


def _parse_context_usage_arg(raw):
    from . import context_usage as context_usage_mod
    decoded, warnings = context_usage_mod.parse_context_usage_json(raw)
    context_usage_mod.emit_warnings(warnings)
    return decoded


def cmd_task_checkpoint(args) -> int:
    from . import record_first
    result = record_first.checkpoint(
        task_id=args.task, task_dir=args.task_dir, actor=args.actor,
        phase=args.phase, summary=args.summary, evidence=args.evidence,
        knowledge_signals=_parse_knowledge_signal_args(args.knowledge_signal_json),
        delivery_signals=args.delivery_signal,
        context_usage=_parse_context_usage_arg(args.context_usage_json), db=args.db,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_task_block(args) -> int:
    from . import record_first
    result = record_first.block(
        task_id=args.task, task_dir=args.task_dir, actor=args.actor,
        reason=args.reason, phase=args.phase, db=args.db,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_task_resume(args) -> int:
    from . import record_first
    result = record_first.resume(
        task_id=args.task, task_dir=args.task_dir, actor=args.actor,
        summary=args.summary, phase=args.phase, db=args.db,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_task_verify(args) -> int:
    from . import record_first
    result = record_first.verify(
        task_id=args.task, task_dir=args.task_dir, actor=args.actor,
        decision=args.decision, summary=args.summary, evidence=args.evidence,
        knowledge_signals=_parse_knowledge_signal_args(args.knowledge_signal_json),
        delivery_signals=args.delivery_signal,
        context_usage=_parse_context_usage_arg(args.context_usage_json), db=args.db,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_task_delivery_converge(args) -> int:
    from . import workflow_records
    result = workflow_records.record_delivery_result(
        task_id=args.task, task_dir=args.task_dir, delivery_status=args.delivery_status,
        reason=args.reason, evidence=args.evidence, before_head=args.before_head,
        after_head=args.after_head, merge_commit=args.merge_commit,
        recovery_condition=args.recovery_condition, blocker_kind=args.blocker_kind,
        responsibility=args.responsibility, residual_risks=args.residual_risk,
        context_usage=_parse_context_usage_arg(args.context_usage_json), db=args.db,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_task_complete(args) -> int:
    from . import record_first
    result = record_first.complete(
        task_id=args.task, task_dir=args.task_dir, actor=args.actor,
        summary=args.summary, db=args.db,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_task_cancel(args) -> int:
    from . import record_first
    result = record_first.cancel(
        task_id=args.task, task_dir=args.task_dir, actor=args.actor,
        reason=args.reason, db=args.db,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def add_task_subparsers(task_parser) -> None:
    """注册 task 命令组的子命令。"""
    sub = task_parser.add_subparsers(dest="subcommand", required=True)

    # task create
    p_create = sub.add_parser("create", help="Create a new task")
    p_create.add_argument("--id", required=True, help="task id (^TASK-[A-Za-z0-9][A-Za-z0-9._-]*$)")
    p_create.add_argument("--project", required=True, help="project id")
    p_create.add_argument("--title", required=False, default="")
    p_create.add_argument("--risk", required=True, choices=["L0", "L1", "L2", "L3"])
    p_create.add_argument("--flow", required=True, choices=["L0", "L1", "L2", "L3"])
    p_create.add_argument("--summary", required=False, default="任务创建")
    p_create.add_argument("--db", required=False, default=None)
    p_create.add_argument("--scaffold", action="store_true", help="Create the V5.2.6 task directory and templates together with the DB task")
    p_create.add_argument("--from-intake", required=False, default=None, help="Adopt pre-task requirement artifacts from an intake directory; implies --scaffold and preserves source")
    p_create.add_argument("--task-dir", required=False, default=None, help="Scaffold destination (default: .tp-spec/tasks/<TASK-ID>)")
    p_create.set_defaults(func=cmd_task_create)

    # V5.2.6 Record-first daily API: business facts, not workflow bookkeeping.
    from . import record_first
    p_cp = sub.add_parser("checkpoint", help="Record meaningful task progress; auto-activates NEW and rebuilds projections")
    p_cp.add_argument("--task", required=True)
    p_cp.add_argument("--task-dir", required=True)
    p_cp.add_argument("--actor", required=True, choices=record_first.ACTORS)
    p_cp.add_argument("--phase", required=True, choices=record_first.PHASES)
    p_cp.add_argument("--summary", required=True)
    p_cp.add_argument("--evidence", action="append")
    p_cp.add_argument("--knowledge-signal-json", action="append", help="structured JSON object with type/summary and optional evidence/source_refs")
    p_cp.add_argument("--delivery-signal", action="append")
    p_cp.add_argument("--context-usage-json", default=None, help="best-effort JSON array of Context Usage receipts; telemetry never blocks checkpoint")
    p_cp.add_argument("--db", default=None)
    p_cp.set_defaults(func=cmd_task_checkpoint)

    p_block = sub.add_parser("block", help="Record a real blocker and set task state BLOCKED")
    p_block.add_argument("--task", required=True)
    p_block.add_argument("--task-dir", required=True)
    p_block.add_argument("--actor", required=True, choices=record_first.ACTORS)
    p_block.add_argument("--reason", required=True)
    p_block.add_argument("--phase", choices=record_first.PHASES)
    p_block.add_argument("--db", default=None)
    p_block.set_defaults(func=cmd_task_block)

    p_resume = sub.add_parser("resume", help="Resolve the explicit blocker and resume ACTIVE work")
    p_resume.add_argument("--task", required=True)
    p_resume.add_argument("--task-dir", required=True)
    p_resume.add_argument("--actor", required=True, choices=record_first.ACTORS)
    p_resume.add_argument("--summary", required=True)
    p_resume.add_argument("--phase", choices=record_first.PHASES)
    p_resume.add_argument("--db", default=None)
    p_resume.set_defaults(func=cmd_task_resume)

    p_verify = sub.add_parser("verify", help="Record actual technical verification; PASS requires real evidence/* and never acts as a phase gate")
    p_verify.add_argument("--task", required=True)
    p_verify.add_argument("--task-dir", required=True)
    p_verify.add_argument("--actor", default="tp-test-engineer", choices=["tp-test-engineer"])
    p_verify.add_argument("--decision", required=True, choices=["PASS", "FAIL", "NEEDS_FIX"])
    p_verify.add_argument("--summary", required=True)
    p_verify.add_argument("--evidence", action="append")
    p_verify.add_argument("--knowledge-signal-json", action="append", help="structured JSON object with type/summary and optional evidence/source_refs")
    p_verify.add_argument("--delivery-signal", action="append")
    p_verify.add_argument("--context-usage-json", default=None, help="best-effort JSON array of Context Usage receipts; telemetry never blocks verification")
    p_verify.add_argument("--db", default=None)
    p_verify.set_defaults(func=cmd_task_verify)

    p_delivery = sub.add_parser("delivery-converge", help="L2/L3: record Integration-owned delivery facts bound to current verification")
    p_delivery.add_argument("--task", required=True)
    p_delivery.add_argument("--task-dir", required=True)
    p_delivery.add_argument("--delivery-status", required=True, choices=["READY", "BLOCKED"])
    p_delivery.add_argument("--evidence", action="append")
    p_delivery.add_argument("--reason", required=True)
    p_delivery.add_argument("--before-head")
    p_delivery.add_argument("--after-head")
    p_delivery.add_argument("--merge-commit")
    p_delivery.add_argument("--recovery-condition")
    p_delivery.add_argument("--blocker-kind", choices=["INTEGRATION_CONFLICT", "VERIFICATION_STALE", "WORKSPACE_DIRTY", "GIT_STATE_INVALID", "HUMAN_DECISION", "OTHER"])
    p_delivery.add_argument("--responsibility")
    p_delivery.add_argument("--residual-risk", action="append")
    p_delivery.add_argument("--context-usage-json", default=None, help="best-effort JSON array of Context Usage receipts; telemetry never blocks delivery")
    p_delivery.add_argument("--db", default=None)
    p_delivery.set_defaults(func=cmd_task_delivery_converge)

    p_complete = sub.add_parser("complete", help="Record terminal completion and expose actual verification facts; no CLOSING phase")
    p_complete.add_argument("--task", required=True)
    p_complete.add_argument("--task-dir", required=True)
    p_complete.add_argument("--actor", required=False, default=None, choices=record_first.ACTORS, help="optional; defaults to current task owner")
    p_complete.add_argument("--summary", required=True)
    p_complete.add_argument("--db", default=None)
    p_complete.set_defaults(func=cmd_task_complete)

    p_cancel = sub.add_parser("cancel", help="human_owner: cancel a non-terminal task without rewriting history")
    p_cancel.add_argument("--task", required=True)
    p_cancel.add_argument("--task-dir", required=True)
    p_cancel.add_argument("--actor", default="human_owner", choices=["human_owner"])
    p_cancel.add_argument("--reason", required=True)
    p_cancel.add_argument("--db", default=None)
    p_cancel.set_defaults(func=cmd_task_cancel)

    # task transition
    p_trans = sub.add_parser("transition", help="Transition task to a new state")
    p_trans.add_argument("--task", required=True, help="task id")
    p_trans.add_argument("--to", required=True, help="target state")
    p_trans.add_argument("--stage", required=False, default=None, help="target stage (default: = --to)")
    p_trans.add_argument(
        "--owner-role",
        required=False,
        default=None,
        help="owner role (default: canonical owner of target state)",
    )
    p_trans.add_argument("--owner-agent", required=False, default=None)
    p_trans.add_argument("--summary", required=True)
    p_trans.add_argument("--evidence", required=False, default=None)
    p_trans.add_argument(
        "--actor-role",
        required=False,
        default=None,
        help="actor role (default: current task.owner_role)",
    )
    p_trans.add_argument("--actor-agent", required=False, default=None)
    p_trans.add_argument("--db", required=False, default=None)
    p_trans.set_defaults(func=cmd_task_transition)


    # task migrate (official in-flight contract migration)
    p_migrate = sub.add_parser("migrate", help="Migrate a non-terminal task to the active contract atomically")
    p_migrate.add_argument("--task", required=True, help="task id")
    p_migrate.add_argument("--task-dir", required=True, help="task directory")
    p_migrate.add_argument("--to", required=False, default=None, help="target contract (default: active VERSION)")
    p_migrate.add_argument("--actor", required=False, default="human_owner", help="migration executor recorded in audit event")
    p_migrate.add_argument("--db", required=False, default=None)
    p_migrate.set_defaults(func=cmd_task_migrate)

    # task retire (administrative inactive marker; preserves last workflow state)
    p_retire = sub.add_parser("retire", help="Retire a non-terminal historical/superseded task without forging completion")
    p_retire.add_argument("--task", required=True)
    p_retire.add_argument("--reason", required=True, help="human-confirmed retirement reason")
    p_retire.add_argument("--superseded-by", required=False, default=None, help="replacement task id, when applicable")
    p_retire.add_argument("--actor", required=False, default="human_owner", choices=["human_owner"])
    p_retire.add_argument("--db", required=False, default=None)
    p_retire.set_defaults(func=cmd_task_retire)

    # task acceptance-override (human_owner audited defer/waive; no false PASS)
    p_accept = sub.add_parser("acceptance-override", help="human_owner: defer or waive selected acceptance criteria without forging PASS")
    p_accept.add_argument("--task", required=True)
    p_accept.add_argument("--task-dir", required=True)
    p_accept.add_argument("--actor", default="human_owner", choices=["human_owner"])
    p_accept.add_argument("--mode", required=True, choices=["defer", "waive"])
    p_accept.add_argument("--scope", choices=["human-pending"], default=None)
    p_accept.add_argument("--ac", action="append", help="acceptance criterion id; repeatable")
    p_accept.add_argument("--reason", required=True)
    p_accept.add_argument("--residual-risk", required=True)
    p_accept.add_argument("--reverify-owner", default=None)
    p_accept.add_argument("--trigger", default=None)
    p_accept.add_argument("--db", default=None)
    p_accept.set_defaults(func=cmd_task_acceptance_override)

    # task migration-plan (read-only upgrade gate)
    p_plan = sub.add_parser("migration-plan", help="Scan all non-terminal tasks for four-way contract/projection consistency")
    p_plan.add_argument("--project", required=True, help="project id")
    p_plan.add_argument("--tasks-root", required=False, default=None, help="tasks root (default: <project.root_path>/.tp-spec/tasks)")
    p_plan.add_argument("--gate", action="store_true", help="return non-zero when any task requires an explicit migration decision")
    p_plan.add_argument("--db", required=False, default=None)
    p_plan.set_defaults(func=cmd_task_migration_plan)

    # task artifact-path (canonical auxiliary output destination)
    p_art = sub.add_parser("artifact-path", help="Resolve the canonical task-local path for SQL/evidence/temp artifacts")
    p_art.add_argument("--task-dir", required=True)
    p_art.add_argument("--kind", required=True, choices=["verification-sql", "test-evidence", "execution-temp"])
    p_art.add_argument("--name", required=False, default=None)
    p_art.add_argument("--role", required=False, default=None, help="required/recommended for execution-temp")
    p_art.add_argument("--ensure", action="store_true")
    p_art.set_defaults(func=cmd_task_artifact_path)

    # task get
    p_get = sub.add_parser("get", help="Get task details")
    p_get.add_argument("--task", required=True)
    p_get.add_argument("--json", action="store_true", help="output as JSON")
    p_get.add_argument("--db", required=False, default=None)
    p_get.set_defaults(func=cmd_task_get)

    # task list
    p_list = sub.add_parser("list", help="List tasks")
    p_list.add_argument("--project", required=False, default=None)
    p_list.add_argument("--state", required=False, default=None)
    p_list.add_argument("--risk", required=False, default=None, choices=["L0", "L1", "L2", "L3"])
    p_list.add_argument("--active", action="store_true", help="Show only active non-terminal, non-retired tasks")
    p_list.add_argument("--db", required=False, default=None)
    p_list.set_defaults(func=cmd_task_list)

    # task validate
    p_val = sub.add_parser("validate", help="Validate task state consistency")
    p_val.add_argument("--task", required=True)
    p_val.add_argument("--db", required=False, default=None)
    p_val.add_argument(
        "--task-dir",
        required=False,
        default=None,
        help="task directory path (enables Record-first artifact truth checks)",
    )
    p_val.set_defaults(func=cmd_task_validate)
