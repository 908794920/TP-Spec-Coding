# Wiki Anchor 恢复

适用条件：Anchor baseline 异常或 cite line 无法恢复时读取。

Anchor baseline 异常时先 `wiki anchors-doctor`。只有 `repairable=true` 才允许 `wiki anchors-repair --apply`；Git 从 committed SHA 读取旧源码，不受 dirty workspace/ref 前移影响；旧对象缺失则报告。FILESYSTEM 的实际字节已偏离 baseline 时不能从 hash 恢复旧签名，需重新验证/full-rebuild。不得手改 `wiki-cite-anchors.json`、hash、snapshot_id 或 cite line。
