# Wiki 源码语义与内容写作

在首次构建或增量更新进入正文写作时读取；语义审计也用同一标准核对。只处理当前选定的稳定源码，遵循 [内容标准](../../../../wiki/rules/content-standard.md)。

## 架构语义五条规则

1. **Currentity**：涉及 workflow、API、command、template、schema、role 或 runtime path 时区分 `CURRENT / COMPATIBILITY / RECOVERY / DEPRECATED / HISTORICAL`。新旧实现并存时，用入口、路由、活动配置、版本契约或实际调用链解释当前主路径。
2. **Existence ≠ Authority**：代码存在、函数可调用、状态兼容或模板保留，不等于当前推荐入口、权威契约或日常主路径；不得仅凭“还能找到”把历史/兼容写成 current。
3. **Responsibility Attribution**：“负责 / 保证 / 决定 / 唯一入口 / 强制”等断言须定位真正 enforcement layer：DB constraint、Runtime transaction、Resolver、Validator、Quality Gate、Agent convention 或 Human policy；缺少直接证据就降低措辞强度。
4. **Pipeline Stage Ownership**：分清 discovery、fingerprint、change classification、Wiki eligibility、topology、planning、AI semantic update、manifest/provenance、verify、coverage、semantic audit 和 baseline commit 的真正 owner，不能混写相邻阶段。
5. **Interface / Scope Exactness**：命令、参数、配置键、阈值、默认值和必选步骤回到实际 parser/schema/config/canonical protocol 或入口核实，不从函数名、旧模板或邻近流程猜不存在的参数；首次 clean build 规则不泛化为日常增量。

同时描述 CURRENT 和 COMPATIBILITY/RECOVERY 时，流程图与数据流必须分叉/标注，不能合成无标签“当前主链”。取舍顺序为：误导当前主路径、责任归因错误、核心模块漏图，优先于引用覆盖完整度，再优先于边角细节；不为形式评分扩写低价值内容。

## 可溯源内容

- content-doc 保持高信息密度七段式；关键实现写真实职责、方法/分支/常量/参数/调用关系。
- 关键结论使用真实 `<cite path="..." line="a-b"/>`，紧邻承载断言的正文 section；引用汇总不能成为唯一 cite 位置。
- cite 首建和更新即有精确行号，极少数单行文件除外；从 `wiki source-read` 的同一固定来源取证，不抄工作区行号。
- 不靠不同类复制逐字套话、metadata-only `reference` dependency 或调分母凑覆盖率；不粘贴大段源码，不为目录完整制造无价值 Markdown。
