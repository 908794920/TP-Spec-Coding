# Wiki Anchor 恢复

适用条件：Anchor baseline 异常或 cite line 无法恢复时读取。

Anchor baseline 异常时先 `wiki anchors-doctor`。只有 `repairable=true` 才允许 `wiki anchors-repair --apply`；若 current source 已偏离 committed snapshot，则旧行签名不可恢复，必须 fail-closed 转重新验证/full-rebuild。不得手改 `wiki-cite-anchors.json`、hash、snapshot_id 或 cite line。
