# Content Systems 配置

权威默认配置：`governance/content-systems.yaml`。用户级 `~/.tp-spec/installation.yaml` 可一次配置 Base/Wiki/Knowledge 系统根；项目 Content Systems 仍作为最高优先级的例外覆盖。

项目可选覆盖：

```text
<workspace>/.tp-spec/config/content-systems.yaml
```

覆盖采用递归 merge；无需复制完整默认配置。

## 零配置路径

```yaml
systems:
  wiki:
    root: ""
  knowledge:
    root: ""
```

解析为：

```text
<workspace>/.tp-spec/wiki
<workspace>/.tp-spec/knowledge
```

## 外部中央存储

```yaml
systems:
  wiki:
    root: "<wiki-system-root>"
  knowledge:
    root: "<knowledge-system-root>"
```

Runtime/CLI 先解析 Wiki System Root，再通过 Repo Registry 解析当前 workspace/repository 的 Wiki scope；取消 Junction 绝不意味着扫描整个中央 Wiki。`.tp-spec/wiki` / `.tp-spec/knowledge` Junction 只用于 legacy 兼容或 IDE 浏览，不是可用性的前提。

## Registry

- 外部 root 下存在 `00-system/repo-registry.yaml` 时，`layout: auto` 自动进入 legacy-central 兼容布局；
- 本地模式默认 registry 为 `.tp-spec/config/wiki-repos.yaml`；
- 已存在 registry 但当前 workspace 无匹配项时 fail-closed；可由 `project-binding.yaml` 的显式 `wiki_id` 提供受控 fallback，不按目录名猜仓库；
- 同一 physical path 通过 canonical path 去重/诊断。

## 稳定源码配置

`systems.wiki.source.source_mode` 默认为 `AUTO`：Git 用 `GIT_REF`，真正非 Git 用 `FILESYSTEM`。正式 Git Wiki 必须配置本地已有的完整远程跟踪引用；空 `stable_ref` 表示尚未配置，不自动选择 remote HEAD 或当前分支。例：

```yaml
systems:
  wiki:
    source:
      stable_ref: refs/remotes/origin/dev
```

`origin/dev` 仅为示例，由用户指定远程与分支。配置按基座默认 → 项目覆盖 → Registry 单仓覆盖合并，再逐仓校验来源。项目默认写入项目 `content-systems.yaml` 的上述位置；单仓例外写入 Registry 对应 `repos[]` 项的 `source.stable_ref`。未覆盖部分继承已有配置，不共享上一个 repo 的运行 SHA；旧 `branch` 字段仅为历史元数据，不参与解析。此处 repo_root 是已有 Resolver 配置，不复制到通用 Skill。

本地引用落后于服务器仍可维护；用户控制何时同步。Wiki 不 fetch/pull，不接纳本地分支未推送提交，也不以工作区代替引用。缺少配置、引用或对象时仅报告受影响仓库及恢复条件，不自动修复源码仓库。FILESYSTEM 不提供指定 Git 分支保证。

来源 pin、离线边界、非 Git 保留、迁移及失败恢复见 [Stable Source](stable-source.md)。

## 配置化与不变量

适合配置：source include/exclude、mass-change threshold、citation coverage、L4 sample size 等。

不允许配置关闭：真实 hash、source/cite existence、UNCERTAIN fail-closed、verify/audit 绑定、PASS 前禁止 baseline commit 等真实性边界。


## Coverage 配置

`systems.wiki.coverage` 只定义“哪些 scanner-visible 文件应该进入 Wiki 文件覆盖率分母”，不改变 source scanner 本身：

```yaml
systems:
  wiki:
    coverage:
      include_globs: []
      no_doc_globs:
        - "**/*Mapper.xml"
        - "**/*Dao.xml"
      excluded_extensions: [".css", ".scss", ".less"]
      markdown_contract_roots: ["agents", "automation", "governance", "skills", "templates", "wiki"]
```

原则：

- scanner 尽量广，负责“不漏变化”；
- coverage denominator 更窄，负责“真实反映应被 Wiki 理解的文件”；
- 所有 exclusion 必须有可查询 reason；
- 项目可以通过 override 增删规则，但不能把不存在/stale 的 dependency 算成 covered；
- `quality.effective_wiki_coverage_warn` 默认 `0.0`，只控制日常质量提示，不把 coverage 变成普遍 Gate；
- `quality.initial_build_effective_coverage_min` 默认 `0.95`，只用于**首次 clean build 的可信 baseline 就绪判断**。它与 warn 阈值语义不同：首次构建低于该值时，CLI 返回/阻止 `BUILD_INCOMPLETE` 进入 full L4 与 baseline commit，避免低成本模型把“无 WARN”误解成“低覆盖也可以结单”；
- 该阈值是成本/收益折中，不要求机械 100%；剩余文件仍必须真实列出，不能通过缩小分母作弊。
