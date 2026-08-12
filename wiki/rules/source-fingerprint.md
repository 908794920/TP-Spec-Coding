# Source Fingerprint 与变更分类

Wiki 使用两类指纹：

- `content_hash`：原始字节 SHA-256，只证明字节身份；
- `normalized_hash`：文本解码并按语言安全归一后的 SHA-256，用于区分 cosmetic 与 semantic。

## 扫描真实性

每次 scan 都会对全部 eligible source **重新计算 raw SHA-256**。`size/mtime` 只作为 provenance/诊断信息，不能单独证明文件未变化。

这是为了防止 archive/re-download/sync 工具在**保持文件大小和时间戳**的情况下替换源码，造成 Wiki 永久漏检。raw hash 未变时可以复用旧 normalized 结果，避免重复文本归一化。

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
