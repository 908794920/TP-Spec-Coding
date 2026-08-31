# Junction 迁移与收敛

适用条件：执行 legacy Junction/symlink 迁移或移除时读取。


迁移必须严格按：

```text
WRITE PROJECT BINDING
→ RE-RESOLVE Base/Wiki/Knowledge
→ 比对旧链接物理 Target
→ 完全一致才可移除链接对象
```

强约束：

- 只删除 Junction/symlink **本身**，绝不删除 Target；
- 若 `.tp-spec/<name>` 是真实目录而非链接，标记 `MANUAL_REVIEW`，不得自动删；
- link target 与 Resolver target 不一致 → `BLOCKED`；
- Knowledge/Wiki project scope 未解析时，不得移除对应链接；
- 旧 Knowledge Registry 尚无 `workspace_roots` 时，可用现有 `.tp-spec/knowledge` Junction/symlink **精确匹配已注册 `10-projects/<id>`** 作为一次性 binding seed；不得按目录名猜；
- 简单 `content-systems.yaml` 只有在与用户 Installation 完全等价时才可选择删除；含项目特有 override 必须保留。
