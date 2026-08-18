# -*- coding: utf-8 -*-
"""User-level Autonomous Maintenance profile contract.

Profiles are durable user intent, not Runtime truth.  They live under
``~/.tp-spec/autonomy/profiles`` (or ``TP_SPEC_USER_ROOT``) and describe the
canonical source scope, the long-lived isolated workspace, unattended policy,
and the scheduler bootstrap prompt.  Task/cycle facts stay in each autonomous
workspace Runtime.
"""
from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from . import db as dbmod
from .path_identity import canonical_path, path_identity_key, same_path
from .version import active_version

PROFILE_SCHEMA = "tp-spec.autonomy-profile/v1"
PROMPT_TEMPLATE_VERSION = "tp-spec.autonomy-prompt/v1"
PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
LEVELS = {"L0", "L1", "L2", "L3"}
CONFIRMATION_POLICIES = {"material", "each_stage"}


class AutonomyProfileError(ValueError):
    pass


def profiles_root() -> Path:
    return dbmod.user_tp_spec_root() / "autonomy" / "profiles"


def profile_path(profile_id: str) -> Path:
    _validate_profile_id(profile_id)
    return profiles_root() / f"{profile_id}.yaml"


def _validate_profile_id(profile_id: str) -> None:
    if not PROFILE_ID_RE.match(str(profile_id or "")):
        raise AutonomyProfileError("PROFILE_ID_INVALID: profile id must match ^[a-z0-9][a-z0-9-]*$")


def _is_same_or_descendant(parent: Path, child: Path) -> bool:
    a = path_identity_key(parent)
    b = path_identity_key(child)
    if a == b:
        return True
    sep = os.sep
    # normpath/normcase in path_identity_key already normalise host-platform aliases.
    return b.startswith(a.rstrip("\\/") + sep)


def validate_isolation(canonical_root: Path, autonomy_root: Path) -> None:
    c = canonical_path(canonical_root)
    a = canonical_path(autonomy_root)
    if _is_same_or_descendant(c, a) or _is_same_or_descendant(a, c):
        raise AutonomyProfileError(
            f"AUTONOMY_PATH_CONFLICT: canonical and autonomous workspace must be physically separated: {c} <> {a}"
        )


def _repo_entry(canonical_root: Path, rel: str, *, mutable: bool) -> Dict[str, Any]:
    rel0 = str(rel or "").strip().replace("\\", "/").strip("/")
    if not rel0 or rel0.startswith("../") or "/../" in f"/{rel0}/":
        raise AutonomyProfileError(f"REPO_PATH_INVALID: {rel!r}")
    path = canonical_path(canonical_root / Path(rel0))
    try:
        path.relative_to(canonical_root)
    except ValueError as exc:
        raise AutonomyProfileError(f"REPO_PATH_ESCAPES_CANONICAL: {rel0}") from exc
    if not path.is_dir():
        kind = "MUTABLE" if mutable else "SUPPORT"
        raise AutonomyProfileError(f"{kind}_REPO_NOT_FOUND: {path}")
    if not (path / ".git").exists():
        kind = "MUTABLE" if mutable else "SUPPORT"
        raise AutonomyProfileError(f"{kind}_REPO_NOT_GIT: {path}")
    proc = subprocess.run(
        ["git", "-C", str(path), "branch", "--show-current"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    branch = proc.stdout.strip() if proc.returncode == 0 else ""
    if not branch:
        raise AutonomyProfileError(f"REPO_BRANCH_UNRESOLVED: {path}")
    return {"id": Path(rel0).name.lower(), "path": rel0, "branch": branch}


def generate_prompt(profile_id: str) -> str:
    return (
        f"对 TP-Spec-Coding autonomy profile `{profile_id}` 执行一次 Autonomous Maintenance Cycle。\n\n"
        "先读取当前用户 Autonomy Profile、当前 TP-Spec-Coding Base 的 autonomy cycle protocol，"
        "以及当前 tp-software-lifecycle。\n\n"
        "不得自行复制、缓存或假设 Workflow；所有 Task 的阶段、角色、深度模式、Verification 与 Delivery "
        "均由当前 tp-software-lifecycle 决定。\n\n"
        "Repo 写入只能发生在 Profile 声明的 Autonomous Workspace；不得直接修改 Canonical Workspace。\n\n"
        "这是无人值守周期，不得 AskUserQuestion。任何 requires_human 决策都必须保留可信 BLOCKED 状态并进入 Digest。\n\n"
        "max_new_tasks_per_cycle 是上限而不是目标；没有高价值改进时允许新增 0 个 Task，"
        "禁止为了达到数量上限制造需求或进行不必要开发。\n\n"
        "遵守 Profile 的 unattended safety budget 和当前 cycle fencing token。\n\n"
        "结束时输出本周期变化、在途 Task、等待用户决策事项、等待 Integration 的成果、"
        "Canonical/Staging drift 和 next_user_actions。"
    )


def build_profile(
    *, profile_id: str, canonical_root: str, canonical_project_id: str,
    autonomy_root: str, mutable_repos: Iterable[str], support_repos: Iterable[str],
    goals: Iterable[str], difficulty_ceiling: str, max_new_tasks: int,
    confirmation_policy: str = "material",
) -> Dict[str, Any]:
    _validate_profile_id(profile_id)
    croot = canonical_path(canonical_root)
    aroot = canonical_path(autonomy_root)
    if not croot.is_dir():
        raise AutonomyProfileError(f"CANONICAL_WORKSPACE_NOT_FOUND: {croot}")
    validate_isolation(croot, aroot)
    level = str(difficulty_ceiling or "").upper()
    if level not in LEVELS:
        raise AutonomyProfileError(f"DIFFICULTY_CEILING_INVALID: {difficulty_ceiling}")
    if confirmation_policy not in CONFIRMATION_POLICIES:
        raise AutonomyProfileError(f"CONFIRMATION_POLICY_INVALID: {confirmation_policy}")
    try:
        ceiling = int(max_new_tasks)
    except (TypeError, ValueError) as exc:
        raise AutonomyProfileError("MAX_NEW_TASKS_INVALID: must be integer") from exc
    if ceiling < 0:
        raise AutonomyProfileError("MAX_NEW_TASKS_INVALID: must be >= 0")
    mutable = [_repo_entry(croot, r, mutable=True) for r in mutable_repos]
    if not mutable:
        raise AutonomyProfileError("MUTABLE_REPO_REQUIRED: select at least one Git repository")
    support = [_repo_entry(croot, r, mutable=False) for r in support_repos]
    mutable_paths = {x["path"] for x in mutable}
    if any(x["path"] in mutable_paths for x in support):
        raise AutonomyProfileError("REPO_SCOPE_CONFLICT: one repository cannot be both mutable and support")
    goal_list = [str(x).strip() for x in goals if str(x).strip()]
    if not goal_list:
        raise AutonomyProfileError("AUTONOMY_GOAL_REQUIRED: at least one maintenance goal is required")
    runtime_id = f"autonomy-{profile_id}"
    prompt = generate_prompt(profile_id)
    return {
        "schema": PROFILE_SCHEMA,
        "profile_id": profile_id,
        "enabled": True,
        "canonical": {
            "workspace_root": str(croot),
            "project_id": str(canonical_project_id or "").strip(),
            "repositories": {"mutable": mutable, "support": support},
        },
        "autonomous": {
            "workspace_root": str(aroot),
            "runtime_project_id": runtime_id,
            "staging": {"branch": f"autonomy/{profile_id}/staging"},
        },
        "context": {
            "wiki_project_id": str(canonical_project_id or "").strip(),
            "knowledge_project_id": str(canonical_project_id or "").strip(),
            "mode": "canonical_read_only",
        },
        "policy": {
            "goals": goal_list,
            "difficulty_ceiling": level,
            "discovery": {
                "max_new_tasks_per_cycle": ceiling,
                "quota_semantics": "ceiling_not_target",
            },
            "execution": {
                "approved_only": True,
                "earliest_after_approval": "next_cycle",
                "same_cycle_batch": True,
                "use_current_orchestrator": True,
            },
        },
        "workflow": {
            "confirmation_policy": confirmation_policy,
            "unattended": {"ask_user_question": False, "requires_human_action": "block_and_digest"},
        },
        "safety": {
            "max_existing_tasks_per_cycle": 5,
            "max_rework_attempts_per_task": 2,
            "max_cycle_minutes": 240,
            "max_pending_user_decisions": 5,
        },
        "automation": {
            "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "generated_with_base": active_version(),
            "prompt": prompt,
        },
    }


def _atomic_dump(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def save_profile(profile: Dict[str, Any], *, overwrite: bool = False) -> Path:
    validate_profile(profile)
    path = profile_path(str(profile["profile_id"]))
    if path.exists() and not overwrite:
        raise AutonomyProfileError(f"PROFILE_ALREADY_EXISTS: {profile['profile_id']}")
    # Each profile must have a distinct autonomous root, but overlapping canonical
    # source scope is allowed and surfaced by doctor/review rather than blocked.
    for existing in list_profiles(ignore_errors=True):
        if existing.get("profile_id") == profile.get("profile_id"):
            continue
        other_root = ((existing.get("autonomous") or {}).get("workspace_root"))
        if other_root and same_path(other_root, (profile.get("autonomous") or {}).get("workspace_root")):
            raise AutonomyProfileError(f"AUTONOMY_ROOT_CONFLICT: already used by profile {existing.get('profile_id')}")
    _atomic_dump(path, profile)
    return path


def validate_profile(profile: Dict[str, Any], *, check_paths: bool = True) -> List[str]:
    errors: List[str] = []
    if not isinstance(profile, dict):
        return ["PROFILE_INVALID: profile must be mapping"]
    if profile.get("schema") != PROFILE_SCHEMA:
        return [f"PROFILE_SCHEMA_UPGRADE_REQUIRED: expected {PROFILE_SCHEMA}, got {profile.get('schema')!r}"]
    try:
        _validate_profile_id(str(profile.get("profile_id") or ""))
    except Exception as exc:
        errors.append(str(exc))
    canonical = profile.get("canonical") or {}
    autonomous = profile.get("autonomous") or {}
    try:
        croot = canonical_path(canonical.get("workspace_root") or "")
        aroot = canonical_path(autonomous.get("workspace_root") or "")
        validate_isolation(croot, aroot)
        if check_paths and not croot.is_dir():
            errors.append(f"CANONICAL_WORKSPACE_NOT_FOUND: {croot}")
        if check_paths:
            for entry in ((canonical.get("repositories") or {}).get("mutable") or []):
                p = canonical_path(croot / str(entry.get("path") or ""))
                if not p.is_dir() or not (p / ".git").exists():
                    errors.append(f"MUTABLE_REPO_NOT_FOUND: {p}")
    except Exception as exc:
        errors.append(str(exc))
    policy = profile.get("policy") or {}
    if str(policy.get("difficulty_ceiling") or "") not in LEVELS:
        errors.append("DIFFICULTY_CEILING_INVALID")
    discovery = policy.get("discovery") or {}
    if discovery.get("quota_semantics") != "ceiling_not_target":
        errors.append("DISCOVERY_QUOTA_SEMANTICS_INVALID")
    try:
        if int(discovery.get("max_new_tasks_per_cycle")) < 0:
            errors.append("MAX_NEW_TASKS_INVALID")
    except Exception:
        errors.append("MAX_NEW_TASKS_INVALID")
    workflow = profile.get("workflow") or {}
    if workflow.get("confirmation_policy") not in CONFIRMATION_POLICIES:
        errors.append("CONFIRMATION_POLICY_INVALID")
    automation = profile.get("automation") or {}
    if not str(automation.get("prompt") or "").strip():
        errors.append("AUTOMATION_PROMPT_MISSING")
    return errors


def load_profile(profile_id: str) -> Dict[str, Any]:
    path = profile_path(profile_id)
    if not path.is_file():
        raise AutonomyProfileError(f"PROFILE_NOT_FOUND: {profile_id}")
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise AutonomyProfileError(f"PROFILE_INVALID: {profile_id}")
    errors = validate_profile(data, check_paths=False)
    if errors:
        raise AutonomyProfileError(errors[0])
    return data


def list_profiles(*, ignore_errors: bool = False) -> List[Dict[str, Any]]:
    root = profiles_root()
    if not root.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for path in sorted(root.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                if not ignore_errors:
                    errors = validate_profile(data, check_paths=False)
                    if errors:
                        raise AutonomyProfileError(errors[0])
                out.append(data)
        except Exception:
            if not ignore_errors:
                raise
    return sorted(out, key=lambda x: str(x.get("profile_id") or ""))



def edit_profile(
    profile_id: str, *, goals: Optional[Iterable[str]] = None, difficulty_ceiling: Optional[str] = None,
    max_new_tasks: Optional[int] = None, confirmation_policy: Optional[str] = None,
) -> Dict[str, Any]:
    profile = load_profile(profile_id)
    if goals is not None:
        vals = [str(x).strip() for x in goals if str(x).strip()]
        if not vals:
            raise AutonomyProfileError("AUTONOMY_GOAL_REQUIRED: at least one maintenance goal is required")
        profile.setdefault("policy", {})["goals"] = vals
    if difficulty_ceiling is not None:
        level = str(difficulty_ceiling).upper()
        if level not in LEVELS:
            raise AutonomyProfileError(f"DIFFICULTY_CEILING_INVALID: {difficulty_ceiling}")
        profile.setdefault("policy", {})["difficulty_ceiling"] = level
    if max_new_tasks is not None:
        try: ceiling = int(max_new_tasks)
        except (TypeError, ValueError) as exc: raise AutonomyProfileError("MAX_NEW_TASKS_INVALID: must be integer") from exc
        if ceiling < 0: raise AutonomyProfileError("MAX_NEW_TASKS_INVALID: must be >= 0")
        discovery = profile.setdefault("policy", {}).setdefault("discovery", {})
        discovery["max_new_tasks_per_cycle"] = ceiling
        discovery["quota_semantics"] = "ceiling_not_target"
    if confirmation_policy is not None:
        if confirmation_policy not in CONFIRMATION_POLICIES:
            raise AutonomyProfileError(f"CONFIRMATION_POLICY_INVALID: {confirmation_policy}")
        profile.setdefault("workflow", {})["confirmation_policy"] = confirmation_policy
    validate_profile(profile)
    _atomic_dump(profile_path(profile_id), profile)
    return profile


def refresh_prompt(profile_id: str) -> Dict[str, Any]:
    profile = load_profile(profile_id)
    auto = profile.setdefault("automation", {})
    auto["prompt_template_version"] = PROMPT_TEMPLATE_VERSION
    auto["generated_with_base"] = active_version()
    auto["prompt"] = generate_prompt(profile_id)
    _atomic_dump(profile_path(profile_id), profile)
    return profile

def set_enabled(profile_id: str, enabled: bool) -> Dict[str, Any]:
    profile = load_profile(profile_id)
    profile["enabled"] = bool(enabled)
    _atomic_dump(profile_path(profile_id), profile)
    return profile


def doctor(profile_id: str) -> Dict[str, Any]:
    path = profile_path(profile_id)
    errors: List[str] = []
    warnings: List[str] = []
    if not path.is_file():
        errors.append(f"PROFILE_NOT_FOUND: {profile_id}")
        return {"schema": "tp-spec.autonomy-doctor/v1", "profile_id": profile_id, "status": "FAIL", "errors": errors, "warnings": warnings}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        errors.append(f"PROFILE_INVALID: {exc}")
        raw = None
    if isinstance(raw, dict):
        errors.extend(validate_profile(raw, check_paths=True))
        automation = raw.get("automation") or {}
        if automation.get("prompt_template_version") != PROMPT_TEMPLATE_VERSION:
            warnings.append("AUTOMATION_PROMPT_REFRESH_RECOMMENDED")
        # Overlapping source scope is legal but should be visible.
        mine = {(x.get("path")) for x in (((raw.get("canonical") or {}).get("repositories") or {}).get("mutable") or [])}
        croot = (raw.get("canonical") or {}).get("workspace_root")
        for other in list_profiles(ignore_errors=True):
            if other.get("profile_id") == profile_id:
                continue
            if croot and same_path(croot, (other.get("canonical") or {}).get("workspace_root") or ""):
                theirs = {(x.get("path")) for x in ((((other.get("canonical") or {}).get("repositories") or {}).get("mutable") or []))}
                if mine & theirs:
                    warnings.append(f"OVERLAPPING_AUTONOMY_SCOPE:{other.get('profile_id')}:{','.join(sorted(str(x) for x in mine & theirs))}")
    return {
        "schema": "tp-spec.autonomy-doctor/v1",
        "profile_id": profile_id,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
    }
