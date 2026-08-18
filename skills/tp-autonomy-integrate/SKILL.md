---
name: tp-autonomy-integrate
version: 5.2.4
description: Autonomous staging 进入 Canonical 的唯一桥：先隔离 Prepare + Verification，再由 human_owner 对唯一目标显式 Apply；多 Repo 使用可恢复 Integration Journal。
---

# tp-autonomy-integrate

## 1. Prepare 永远先于 Apply
用户准备接收一个或多个按顺序的 READY Batch 时：

```text
tp-spec autonomy integrate prepare --profile <id> --batch <BATCH> ... --json
```

Prepare 在 `.tp-spec/autonomy/integration/<ID>/repos/` 临时 clone 当前 Canonical，并将 Autonomous commit range 重放到**当前 Canonical HEAD**。冲突/脏工作区/分支变化均 fail-closed，真实 Canonical 不参与试错。

## 2. 重新验证 Candidate
Prepare 结果初始是 `NEEDS_VERIFICATION`。由当前 `tp-workflow-orchestrator`/`tp-test-engineer` 在 integration candidate 上执行必要验证，将非空 evidence 放入该 Integration 的 `evidence/`，再：

```text
tp-spec autonomy integrate verify ... --decision PASS --evidence <...>
```

这仍是 evidence traceability，不冒充密码学 execution attestation。

## 3. Apply Gate
真正 Apply 只有在：
- Verification PASS；
- Prepare 绑定的 Canonical pre-ref 仍成立；
- 目标明确且唯一；
- human_owner 明确表达接受意图；
- 当前 Base capability 允许 Apply；

时调用：

```text
tp-spec autonomy integrate apply --profile <id> --integration <ID>
```

不要增加密码/重复确认。如果当前存在多个目标而用户只说“合并吧”，先消歧。

## 4. 多 Repo
所有 Repo Prepare READY 才允许 Apply。Apply 使用 Integration Journal，逐 Repo 做可恢复 ref transition；不宣称跨多个独立 Git Repo 是 ACID 原子事务。Crash 后必须能确定每个 Repo 是 pre/target/RECOVERY_REQUIRED，再 finish-forward 或按正式 recovery 处理。

## 5. 禁止
- 目录覆盖 Canonical；
- 无 Verification Apply；
- Scheduler/unattended cycle 自动 Apply；
- `--force-unsafe` 绕过 Pilot；
- 自动把 Canonical rebase/merge 到长期 staging。
