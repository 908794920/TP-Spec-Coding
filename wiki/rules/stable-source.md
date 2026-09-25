# Wiki Stable Source

正式 Wiki 只描述被选定的稳定源码，不跟随尚未接受的 Work、集成候选或 dirty workspace。规则由 `cli/wiki/stable_source.py` 实现，沿用现有 Snapshot、Manifest、Plan、Verification、Audit 和 Repo Registry，不新增 Wiki 账本或 Preview Wiki。

## 来源选择

配置位置是现有 `systems.wiki.source`；Registry 的单仓 `source` 覆盖同名配置。

```yaml
systems:
  wiki:
    source:
      source_mode: AUTO
      stable_ref: refs/remotes/origin/dev
```

`origin/dev` 仅为例子，不是内置远程或默认分支。`AUTO` 在真实 Git 仓库使用 `GIT_REF`，非 Git 使用 `FILESYSTEM`。Git 必须显式配置合法、本地存在且非符号引用的 `refs/remotes/<remote>/<branch>`。不接受短分支名、本地分支、tag、直接配置的 SHA、HEAD、修订表达式或 remote HEAD 别名；未配置即停止该仓库，不猜默认分支。配置合并后逐仓检查，旧 Registry `branch` 不参与选择。内部读取已固定的完整 SHA 仍是必要能力，不受配置值限制影响。

Wiki 不执行 fetch、pull、checkout、reset、merge、创建 worktree 或其他源码仓库写入。读取 Git 对象时禁用 replace objects、隐式 lazy fetch、外部 diff/textconv 和网络 transport；缺失本地引用或对象明确失败，不以同步作为自动修复。远程跟踪 ref 只代表本地已有状态，允许落后于服务器，不声称已联网同步远端最新提交。用户自行决定何时同步；更新引用后下一轮维护采用新提交。工作区、暂存区、未跟踪文件及本地分支未推送提交不进入来源。真正非 Git 的 FILESYSTEM 仍按实际文件读取，不提供指定分支保证；Git 不能降级为 FILESYSTEM。

诊断区分 `STABLE_REF_REQUIRED`（未配置）、`STABLE_REF_INVALID`（类型/格式不符）、`STABLE_REF_SYMBOLIC`（符号别名）、`STABLE_REF_UNAVAILABLE`（本地引用不可用）和 `STABLE_REF_OBJECT_UNAVAILABLE`（提交对象不可用）；文件对象或历史读取失败沿用既有 Git 来源错误。只报告对应仓库和恢复条件，不代替用户执行同步。

Git 检出目录、linked worktree、bare repo 和仓库子目录均使用同一对象读取机制。子目录以 `repo_prefix` 限定范围；单仓 Wiki 不跨 Registry scope。选中的 symlink 不跟随 dirty 工作区；未排除的 gitlink 返回需核对错误。确需子模块时独立注册实际仓库并在父仓明确排除其路径，不能把未获取的 submodule 当成已扫描源码。

## 一次运行、一份固定源码

`maintain` / `scan` / `build` 在开始时把 stable_ref 固定为不可变 commit，随后从 Git tree/blob 读取。所有机器 hash、VERSION 断言、覆盖率、引用行数、引用锚点和审计来源都绑定这份 identity。

AI 编写或审计时从正式入口按需读同一份源码：

```text
tp-spec wiki source-read --workspace-root <workspace> --repo <id> --path src/Service.java --start-line 12 --end-line 38
tp-spec wiki source-read --workspace-root <workspace> --repo <id> --path src/Service.java --baseline
```

默认选择完整的 pending run，否则读成功 baseline；`--baseline` 明确读取已提交来源。返回完整 source identity、原始字节 hash、编码、行范围和文本；不能用工作区行号替换。普通源码调研仍可读工作区，但不得把它作为这次正式 Wiki 的引用证据。

运行途中 ref 向前移动，不改变已经固定的 candidate；follow-up 命令继续处理该 SHA，下次 `maintain` 再处理新的稳定提交。若主动重新 `scan/maintain` 并取得了不同候选，旧 Verification/Audit 不再适用。维护配置/规则变化后必须重新 staging，不能旧计划新规则混用。

非 Git 保留每次全量 raw hash/local snapshot 和提交前稳定性核对，不依赖 size/mtime。`source-read` 要求文件字节与记录相符；历史内容已经变化时不能从 hash 重建旧文本，应如实报告。Git 项目不能用显式 `FILESYSTEM` 绕回 dirty 工作区。

## 增量与零 LLM 快路径

成功 baseline 的 SHA、stable_ref、repo_prefix 和维护配置/规则 digest 一致，持久 Wiki subject 未变、上次完整成功、没有 pending/未收敛验证和显式修复要求时，`wiki maintain` 返回：

```json
{"state":"NO_CHANGE","fast_path":true,"source_scanned":false,"requires_ai_update":false,"llm_dispatch":false}
```

该路径在源码枚举、归一化、planner 之前结束，不调用模型；只读取来源 identity、配置/规则及 Wiki subject。CLI 本身不实现 LLM 客户端，宿主必须按结果选择是否派发作者/审计模型。要实现**整次调度零 LLM**，宿主须在唤醒模型前执行这个确定性命令；已经先唤醒对话模型的纯 prompt 定时器只能免除后续语义调用，不能宣称本次唤醒也免费。本版不改调度频率、不自动修改用户 Scheduler 配置。

有新 commit 时从成功 commit 到本次 commit 计算 diff，复用未变 blob 的指纹，仅重读变动文件；再沿现有 dependency / section / topology 映射到必要文档。删除与重命名分别进入删除/新增及现有 normalized move 分析，不做源码逐文件镜像。源范围外或 empty commit 只需确定性 finalize 并提交新来源 SHA，不调用作者模型。

首次初始化、上次失败/未完成、相关配置/规则变化、未核验的 Wiki subject 变化和显式修复不能走成功快路径。`--repair [--document <Wiki-relative path> ...]` 复用现有计划与 L4：仅显式修复且其他输入稳定时可限定已登记文档；规则/主体等全局变化不以局部参数隐藏。没有 `--repair` 不能单独传 `--document`。同一有效 pending 输入重试保持 change_set_id 和有效 receipt；仍由原有 subject/source/digest 核验判断是否可复用。

`FILESYSTEM` 无变化也返回 NO_CHANGE，但 `fast_path=false`、`source_scanned=true`；不得把文件系统全量 hash 冒充 Git 零扫描。质量 L1–L4、coverage、mass-change guard 和既有日常/周度审计职责不被取消。

## 基线、证据与恢复

Snapshot v1 增加兼容字段：`source`（source_mode / stable_ref / commit / repo_prefix）、`source_policy_digest`、`maintenance_digest`、`scan_mode`。原 `snapshot_id` 仍是内容指纹，不与 commit SHA 混为一谈。成功 `completion` 保存时间、change_set_id、Wiki subject digest、Verification/Audit 结果与受影响文档；临时 receipt 清理后仍能追溯本次推进依据。验证结果与语义审计既绑定 subject，也绑定 source / maintenance digest。

只有当前 Verification PASS、需要时真实 L4 PASS、first-build readiness 满足且源码有效，才能由 `snapshot-commit` 替换成功 baseline。失败保留旧 baseline；原子写入失败可重试。baseline 已替换而临时文件清理失败时明确返回 `COMMITTED`、`baseline_advanced=true` 和 `cleanup_pending`，不得误报“未推进”；下次维护重新核验残留状态，不直接快跳过。

多仓独立 pin / staging / commit。某仓 ref、历史或配置失败，在结构化结果中明确列出，健康仓仍可处理；`committed_repos` 是实际成功集合，不宣称跨仓原子事务。本协议沿用单 repo 串行写入，不提供多个并行作者修改同一 Wiki 的隔离保证。

历史 baseline 和证据保留：`source-read --baseline`（无 pending 时的 source-read 同样读取 baseline）与既有 anchor doctor/repair 可回读对象仍在的历史 SHA，即使旧 stable_ref 已不符合新配置要求；这不允许继续推进旧来源。旧策略 pending 由维护摘要检查阻止续用，需重新准备。新策略的合法 pending 不因引用移动而换 SHA，配置或规则变化仍使其失效。

非 Git 的旧 hash baseline 可直接进入正常扫描和验证，以实际字节补记 FILESYSTEM 身份；不要求无意义的 commit 初始化。正式 Git 的旧 baseline 没有来源身份、由本地分支/tag/SHA 改为远程跟踪引用，或更换已登记的远程/分支时，显式初始化：

```text
tp-spec wiki maintain --workspace-root <workspace> --repo <id> --initialize-source
```

这是显式初始化 candidate，旧 baseline 在全范围必要验证和审计成功前仍保持原样。`--initialize-source` 不跳过不可用旧 commit 或非祖先历史检查。非祖先/无法证明 ancestry、丢失对象、错误 ref 只报告并保留原 baseline；需要由有授权者先恢复可比本地历史或另行确定新的独立 Wiki 来源，不能删 metadata、填假 SHA 或以静默全库重扫掩盖。

源码回滚本 Patch 不会自动迁移实际 Wiki 数据。若已启用稳定来源，不应让旧版工作区读取器继续写同一 Wiki；在授权下恢复版本与对应数据快照，保留现有证据。
