from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

PREFERENCES_SCHEMA = 'tp-spec.preferences/v1'
SUPPORTED_CONFIRMATION_POLICIES = {'material', 'each_stage'}


class PreferenceError(ValueError):
    pass


def _policy(value: Any, *, source: str) -> str:
    policy = str(value or '').strip()
    if policy not in SUPPORTED_CONFIRMATION_POLICIES:
        raise PreferenceError(f"{source}: confirmation_policy must be one of {sorted(SUPPORTED_CONFIRMATION_POLICIES)}")
    return policy


def read_user_confirmation_policy(preferences_path: Path) -> Optional[str]:
    p = Path(preferences_path)
    if not p.is_file():
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding='utf-8-sig')) or {}
    except Exception as exc:  # noqa: BLE001
        raise PreferenceError(f'{p}: invalid YAML: {exc}') from exc
    if not isinstance(data, dict) or data.get('schema') != PREFERENCES_SCHEMA:
        raise PreferenceError(f'{p}: schema must be {PREFERENCES_SCHEMA}')
    workflow = data.get('workflow')
    if workflow is None:
        return None
    if not isinstance(workflow, dict):
        raise PreferenceError(f'{p}: workflow must be a mapping')
    if 'confirmation_policy' not in workflow:
        return None
    return _policy(workflow.get('confirmation_policy'), source=str(p))


def resolve_confirmation_policy(cli_policy: Optional[str], preferences_path: Path, base_default: str) -> str:
    if cli_policy is not None:
        return _policy(cli_policy, source='CLI')
    configured = read_user_confirmation_policy(preferences_path)
    return configured if configured is not None else _policy(base_default, source='Base default')


def write_user_confirmation_policy(path: Path, policy: str) -> Path:
    policy0 = _policy(policy, source='user preference')
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any]
    if p.is_file():
        try:
            loaded = yaml.safe_load(p.read_text(encoding='utf-8-sig')) or {}
        except Exception as exc:  # noqa: BLE001
            raise PreferenceError(f'{p}: invalid YAML: {exc}') from exc
        if not isinstance(loaded, dict) or loaded.get('schema') != PREFERENCES_SCHEMA:
            raise PreferenceError(f'{p}: schema must be {PREFERENCES_SCHEMA}')
        payload = dict(loaded)
    else:
        payload = {'schema': PREFERENCES_SCHEMA}
    workflow = payload.get('workflow')
    if workflow is None:
        workflow = {}
    if not isinstance(workflow, dict):
        raise PreferenceError(f'{p}: workflow must be a mapping')
    workflow = dict(workflow)
    workflow['confirmation_policy'] = policy0
    payload['workflow'] = workflow
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(text, encoding='utf-8', newline='\n')
    tmp.replace(p)
    return p


def event_digest(event: Dict[str, Any]) -> str:
    stable = {
        'id': int(event.get('id') or 0),
        'event_type': str(event.get('event_type') or ''),
        'actor_role': str(event.get('actor_role') or ''),
        'to_stage': str(event.get('to_stage') or ''),
        'summary': str(event.get('summary') or ''),
        'detail_json': str(event.get('detail_json') or ''),
        'created_at': str(event.get('created_at') or ''),
    }
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _canonical_digest(data: Dict[str, Any]) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def build_boundary_binding(*, task_id: str, source_stage: str, source_role: str,
                           source_event_id: int, source_event_digest: str,
                           target_stage: str, target_role: str,
                           execution_mode: str, confirmation_kind: str = 'ordinary') -> Dict[str, Any]:
    kind = str(confirmation_kind or '').strip().lower()
    if kind not in {'ordinary', 'material'}:
        raise ValueError('confirmation_kind must be ordinary|material')
    core: Dict[str, Any] = {
        'confirmation_kind': kind,
        'source_stage': str(source_stage), 'source_role': str(source_role),
        'source_event_id': int(source_event_id), 'source_event_digest': str(source_event_digest),
        'target_stage': str(target_stage), 'target_role': str(target_role),
        'execution_mode': str(execution_mode),
    }
    core['route_digest'] = _canonical_digest({'task_id': str(task_id), **core})
    return core


def workflow_confirmation_matches(event: Dict[str, Any], binding: Dict[str, Any]) -> bool:
    detail = trusted_event_detail(
        event, event_type='WORKFLOW_CONFIRMATION', producer='workflow_confirm', actor='human_owner'
    )
    if detail is None:
        return False
    return all(detail.get(key) == expected for key, expected in binding.items())


def build_wake_prompt(*, task_id: str, workspace: str, source_stage: str, source_role: str,
                      target_stage: str, target_role: str, execution_mode: str) -> str:
    workspace_part = f' 工作区：`{workspace}`。' if str(workspace or '').strip() else ' '
    return (
        f'继续 Task `{task_id}`。{workspace_part}'
        f'已完成 `{source_stage} / {source_role}`；下一步 `{target_stage} / {target_role} / {execution_mode}`。'
        '先读取该 Task Runtime 并运行 `workflow next` 核验；一致后仅加载返回 Skill。'
    )


def trusted_event_detail(event: Dict[str, Any], *, event_type: str, producer: str,
                         actor: str) -> Optional[Dict[str, Any]]:
    if str(event.get('event_type') or '') != event_type or str(event.get('actor_role') or '') != actor:
        return None
    try:
        detail = json.loads(event.get('detail_json') or '{}')
    except Exception:
        return None
    if not isinstance(detail, dict):
        return None
    required = ('transaction_id', 'producer', 'schema_version', 'task_id', 'actor_role', 'created_at')
    if any(not detail.get(key) for key in required):
        return None
    if str(detail.get('producer') or '') != producer or str(detail.get('actor_role') or '') != actor:
        return None
    if str(detail.get('task_id') or '') != str(event.get('task_id') or ''):
        return None
    if str(detail.get('created_at') or '') != str(event.get('created_at') or ''):
        return None
    workflow_version = str(event.get('workflow_version') or '')
    if workflow_version and str(detail.get('schema_version') or '') != workflow_version:
        return None
    return detail


def find_matching_confirmation(events: list[Dict[str, Any]], binding: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for event in reversed(events):
        if workflow_confirmation_matches(event, binding):
            return event
    return None
