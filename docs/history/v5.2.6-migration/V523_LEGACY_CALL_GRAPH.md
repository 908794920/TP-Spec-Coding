# V5.2.3 Legacy Call Graph

Active references that require split/migrate/retire:

- `cli/commit_cmd.py:46` — `from .transition_service import validate_transition`
- `cli/commit_cmd.py:398` — `Hardening：替换 AI-A 的空实现。委托 cli/transition_service.validate_transition`
- `cli/commit_cmd.py:543` — `from . import transition_service as ts`
- `cli/commit_cmd.py:1104` — `"""普通 commit 统一转调 transition_service.transition_task（唯一状态写入服务）。`
- `cli/commit_cmd.py:1109` — `from .transition_service import transition_task`
- `cli/config_loader.py:387` — `from .legacy_workflow import LEGACY_STATE_OWNERS`
- `cli/config_loader.py:388` — `legacy_owner = LEGACY_STATE_OWNERS.get(state)`
- `cli/event_cmd.py:206` — `转调共享 transition_service.transition_task（共享 validator + durable journal +`
- `cli/event_cmd.py:284` — `# ---- 管理员恢复模式：转调共享 transition_service ----`
- `cli/event_cmd.py:300` — `from .transition_service import transition_task`
- `cli/event_cmd.py:442` — `# V5.2.3 Hardening：显式管理员恢复模式（走共享 transition_service）`
- `cli/event_policies.py:38` — `# ARCHITECTURE_REVIEW_STALE 定义于 cli/transition_service.py（保持同义常量）`
- `cli/legacy_workflow.py:11` — `LEGACY_STATE_OWNERS = {`
- `cli/legacy_workflow.py:28` — `LEGACY_TRANSITIONS = {`
- `cli/review_cmd.py:219` — `from .transition_service import YamlValidationError, parse_frontmatter_yaml`
- `cli/validator.py:11` — `transition_service rules used by ``tp-spec commit`` (requires DB + task id).`
- `cli/validator.py:71` — `from . import transition_service as ts`
- `cli/workflow_loader.py:306` — `from .legacy_workflow import LEGACY_STATE_OWNERS, LEGACY_TRANSITIONS`
- `cli/workflow_loader.py:308` — `for state, owner in LEGACY_STATE_OWNERS.items():`
- `cli/workflow_loader.py:311` — `for state, next_states in LEGACY_TRANSITIONS.items():`
- `cli/yaml_checks.py:19` — `commit_cmd / transition_service / PowerShell validator 共用本模块，保证`
- `manifest.sha256:87` — `8785AD0953E68351C9C76DBE7C2F938B2005084DDE8809BCABC641020E30F13E  cli/legacy_workflow.py`
- `manifest.sha256:116` — `830817C07327E064307EAA66AF28F30F6DACC95E2B71B951C255A0B368BC8B15  cli/transition_service.py`
- `scripts/Test-TpSpecTask.ps1:752` — `# 与 Python cli/transition_service.validate_transition 语义对齐（fail-closed）。`

Known direct active imports requiring explicit migration:
- `cli/config_loader.py` → `LEGACY_STATE_OWNERS`
- `cli/workflow_loader.py` → `LEGACY_STATE_OWNERS`, `LEGACY_TRANSITIONS`
- `cli/commit_cmd.py` / `cli/event_cmd.py` / `cli/review_cmd.py` / validators → legacy transition helpers
