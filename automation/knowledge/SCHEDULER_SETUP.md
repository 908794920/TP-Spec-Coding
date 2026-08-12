# Conversational Knowledge Scheduler Setup

Knowledge maintenance is scheduled by waking a **conversational model session**. The scheduler is not the Knowledge Runtime.

## What to put in the scheduler

Store only the contents/intent of `SCHEDULER_BOOTSTRAP.md` as the scheduled prompt. Do not copy `daily-maintenance.md`, SKILL rules, CLI steps, model names or absolute Knowledge paths into the scheduler configuration.

The scheduled conversation should start with the **project workspace root** as context. From there it reads the user Installation and resolves the current physical Base Root, Knowledge System Root, and project-scoped Knowledge root. Project-side Junctions are not required.

## Required capabilities

The scheduled conversational model must be able to:

1. read the current Base and workspace files;
2. execute the physical Base `scripts/Invoke-AiWorkCli.ps1 knowledge ...` or an equivalent installed `ai-work knowledge ...` command;
3. edit only the resolved Knowledge Vault when the canonical protocol permits it;
4. preserve the previous trusted baseline on failure.

It does not need an embedding service or a second Knowledge-specific daemon.

## Unattended contract

- Never use `AskUserQuestion` during the scheduled run.
- Project assignment, destructive delete/overwrite, uncertain merge/split and evidence conflicts are `NEEDS_REVIEW`.
- A normal daily schedule does not create the first trusted baseline. Initial migration/bootstrap is an explicit human-owner activity.
- A failed run must not advance snapshot/baseline merely so the next run looks clean.
- The final message is a compact maintenance report, not a long explanation.

## Cadence

Cadence is owned by the external scheduler/user. Daily is a reasonable default for a Vault that changes frequently; the Base does not encode a mandatory clock time. Each run reads the current Base protocol, so changing the Base does not require rewriting the scheduled prompt.
