# Knowledge Evidence Standard

## Evidence classes

Knowledge accepts four evidence classes:

- `source`: registered external/source material, normally a stable `SRC-*` identity or source-registry record
- `task`: TP-Spec-Coding Task evidence, normally `TASK-*` plus a locator when available
- `code`: source-code evidence with repository/path/line or symbol locator
- `external`: another durable external reference with enough identity to re-check

Existing canonical notes using `source_refs: [TASK-...]` remain valid compatibility data. New or materially revised notes should prefer `evidence_refs` when a simple source ID cannot describe the evidence precisely.

## Structured form

```yaml
evidence_refs:
  - type: task
    ref: TASK-20260809-001
    locator: .ai-work/tasks/TASK-20260809-001/evidence/final.md
  - type: code
    ref: TP_Voyager
    locator: agent_runtime/service.py#L120-L168
```

`sha256` may be supplied when byte identity matters.

## Verification rule

A strong claim such as "X guarantees Y", "X is the current entry", "this value is N", or "this behavior is mandatory" requires evidence that actually enforces/supports that statement. System outcome must not be misattributed to the wrong layer.

Evidence resolution is fail-closed where the Base has an authoritative local root. If a `TASK-*` root is not configured, the ref may remain externally resolvable, but the agent must not claim it was locally re-verified.
