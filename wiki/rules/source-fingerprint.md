# Source Fingerprint 与变更分类

Wiki 使用两类指纹：

- `content_hash`：原始字节 SHA-256，只证明字节身份；
- `normalized_hash`：文本解码并按语言安全归一后的 SHA-256，用于区分 cosmetic 与 semantic。

## 扫描真实性

来源协议见 [Stable Source](stable-source.md)。`FILESYSTEM` 每次 scan 对全部 scanner-visible source 重新计算 raw SHA-256；`size/mtime` 只作诊断，不能单独证明未变，防止 archive/re-download/sync 保持大小和时间戳却替换源码。

`GIT_REF` 首次或 source policy 变化时对固定 commit 做 inventory；日常使用 commit diff，仅对变动 blob 计算指纹，未变对象复用基线结果。成功 SHA 和维护策略不变的 `maintain` 快路径不进入 scan。raw hash 相同且归一化配置/规则也相同时才复用 normalized 结果，不能跨算法版本沿用旧判断。

## 维护规则指纹

`maintenance_digest` 绑定合并后的 source/snapshot/quality/coverage 配置，以及内容维护实现、机器产物 schema 和约束 AI 维护/审计的规则正文。`cli/wiki` 中的维护编排与共享实现、`cli/sensitive_scanner.py`、`wiki/rules`、`wiki/schema`、Wiki Agent、维护/构建/审计/恢复/调度 Skill 与 `automation/wiki` 继续按实际文件字节计算；不以 Skill 的 `id/version` 代替正文。

检索实现 `cli/wiki/retrieval.py`、检索命令 `cli/wiki/retrieval_commands.py` 和 `skills/wiki/tp-wiki-retrieval/` 不属于内容维护规则，不进入该指纹。检索命令独立注册，避免只改检索参数就改变维护编排文件。共享的维护入口仍全文绑定，不能为消除误触发而排除其真实门禁。

这只隔离检索投影与内容维护的失效范围：源码文件变化检测、运行中规则变化拒绝、Wiki subject 绑定，以及检索侧的文档/manifest/目录指纹和索引 `STALE` 检测继续独立生效。

修改涉及 maintenance 规则前，使用 `<BaseRoot>/scripts/tp-spec.ps1 wiki policy-archive --output-root <归档目录>` 保存当前完整规则原字节，包括未提交工作树内容；已保存且仍与修改前字节一致的快照可复用。默认 `--rule-scope maintenance`，仅为需要匹配的历史全规则范围显式使用 `--rule-scope whole-all`。命令返回 `archive_root`、`rules_digest` 和 `file_count`；同字节既有归档可幂等复用，异内容拒绝覆盖。交付须明确归档及审查证据路径，不能只交 hash 或版本。归档成功不等于语义审查或 PASS，也不自动写正式 Wiki 或回执。

历史 before 若只含变更文件，须以实际旧 hash 校验各文件，再补入经核实未变的其他规则原字节组成完整归档；无法证明字节时不得猜测，报告具体缺口。

新 snapshot 同时保存 `maintenance_components`：四类有效配置和逐文件规则 SHA，聚合摘要仍严格绑定完整字节。规则变化须审查实际差异；不能仅因多个仓共同命中或源码零变化就认定语义不受影响。

确认差异只影响确定性处理、旧语义结论仍适用时，使用正式 `wiki policy-review`，显式提供旧 Base Git ref 或原始字节归档、旧规则范围、实际审查说明与证据文件。CLI 必须以旧规则和当前有效配置精确重现旧 `maintenance_digest`；无法重现、配置变化、旧成功验证义务不明或存在 FAIL 时不接受。正常维护不遍历 Git 历史，也不自动推断政策等价。

有效 review 只消除 `MAINTENANCE_POLICY_CHANGED` 引起的全仓语义复核理由；真实源码变化、正文/持久 metadata 变化、repair、旧 FAIL 和 topology 义务继续生效。manifest 仅两个机器时钟 scalar 和严格匹配本轮交易 ID 的字段可在内容身份中归一化，完整 subject 仍绑定 verify/commit。缺少旧 subject 原文、当前 fullsubject 已不匹配旧成功 baseline 的仓不因此豁免。

重新 `maintain → manifest-refresh → verify → coverage → 必要 L4 → snapshot-commit` 正式收口，不手改摘要。verify 和 commit 重新核对政策、配置、证据 SHA 及 review 绑定。确定性收口保留原语义审计的来源、时间和限制，不生成新的 L4 PASS；旧合法成功记录若明确无需 L4 且未保存 L4，继续标记 `LEGACY_L4_NOT_RECORDED`，不能升级为已审计。证据不足时保留旧 baseline、报告缺口；此迁移不要求重写全部 Wiki 或执行全库构建。

## 编码层

先把字节解码为 Unicode，再做 semantic normalization：

- UTF-8 / UTF-8 BOM；
- UTF-16 BOM；
- UTF-32 BOM；
- GB18030（兼容常见 GBK/GB2312 旧中文 Java 工程）；
- 无法可靠解码或疑似错误文本时 → `UNCERTAIN`。

因此同一逻辑文本仅从 UTF-8 改成 UTF-16/GB18030，可得到相同 normalized hash；不能确认的编码绝不直接触发全量 AI 重写。

## 归一化边界

明确吸收：

- CRLF/LF；
- BOM/no-BOM；
- 文件末尾 newline；
- trailing whitespace；
- 空白行；
- 在能安全处理的语言中，纯注释变化。

不得吞掉语言语义：

- Python 缩进通过 tokenization 保留；
- YAML leading indentation 保留；
- JS/TS/Vue 的脚本内容在没有完整 parser 时采取保守策略：宁可产生一次 false-semantic，也不能把真实改动错判 cosmetic；
- `.properties` 默认兼容既有 key-only normalized 策略，值变化不触发语义重写；可在配置中调整策略。

normalized 算法只有 `cli/wiki/source.py` 一份实现，manifest、verify、snapshot 都调用它，禁止再次复制三套算法。

## Change Kind

```text
TOUCHED_ONLY
COSMETIC
SEMANTIC
STRUCTURAL
DELETED
UNCERTAIN
```

`COSMETIC` 默认只更新 provenance/hash，不调用模型修改正文。

## Mass Change Guard

大批 raw change 且绝大多数 normalized-equivalent → `BULK_COSMETIC_DRIFT`，禁止 Token 爆炸式重写。

大批 normalized change → `MASS_CHANGE_REVIEW_REQUIRED`。模型必须先判断重新下载、encoding、formatter、include/exclude 漂移或真实大迁移；确认真实大迁移后，`wiki plan --allow-mass-change` 必须同时记录实际 review reason。

## 精确 cite 行号与 Cosmetic Drift

`normalized_hash` 不变只说明源码语义等价，不代表物理行号不变。注释/空行增删可能让 `<cite line="a-b">` 整体位移。

因此每次成功 `snapshot-commit` 都生成机器拥有的：

```text
meta/wiki-cite-anchors.json
```

它绑定已提交 `snapshot_id`，只保存被引用 source 的**哈希化行签名**与 citation 坐标，不复制源码正文。后续 `COSMETIC` 变化时，`wiki manifest-refresh` 使用旧/新行签名对齐并确定性重定位 cite 行号；这一过程不调用模型。

如果 anchor baseline 缺失、与 source baseline 不匹配或无法唯一安全对齐：

```text
CITE_ANCHOR_RELOCATION_UNAVAILABLE
```

必须 fail-closed，不允许保留“仍在范围内但已经指错位置”的旧行号。`wiki verify` 会再次检查是否还有待执行的 deterministic relocation，禁止绕过 `manifest-refresh`。

### Anchor Baseline 受控恢复

历史版本若留下部分 `wiki-cite-anchors.json`，先运行 `wiki anchors-doctor` 比较 manifest precise cited sources 与 committed anchor sources。

`wiki anchors-repair --apply` **不推进 source snapshot**，仅在以下条件全部成立时允许从当前 source/manifest 重建完整 anchor metadata：

- anchor/schema 已迁移到当前 `tp-spec.*`；
- anchor `snapshot_id` 与 committed `wiki-snapshot.json` 一致；
- 当前 source snapshot 与 committed source baseline 完全一致；
- 当前 Wiki Markdown 与 manifest hash/citation 一致；
- 当前 Wiki Markdown 仍与旧 anchor 的 document hash subject 一致。

Git anchor 恢复读取成功 baseline 的不可变 commit，不读取已移动的 stable_ref 或 dirty 工作区；旧对象仍可用时可按上述条件重建。FILESYSTEM 的实际字节若已变化（即使只是 COSMETIC），hash 无法反推缺失旧签名，必须重新验证后建立新 baseline。两种模式均不得伪造旧行签名。
