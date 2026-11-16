# MySQL / SQL

与[共用标准](../coding-standards.md)一起使用。确认实际 MySQL 版本、SQL mode、对象命名与大小写配置，区分独立 SQL 和 ORM/Mapper 内嵌语句。

- 查询分组应让 SELECT、JOIN/ON、过滤、聚合及排序容易对应。字段同名或多表关联时，用明确字段来源与可理解别名。
- 关键字大小写和排版按项目约定；已有表、列、索引名属于兼容对象，不能为了风格批量改名。
- 结合契约核对 NULL、聚合、JOIN 行数和过滤位置；需要索引、事务、锁或性能判断时按需读[数据库工程](../../../database-engineering/SKILL.md)。无需以 SQL 只读审查名义连接或写真实数据库。
- 必要注释说明业务统计口径、非显然条件和迁移约束。不要通过删条件、改变 JOIN、补 WHERE 或改默认值来“美化”语句。

例如已明确来源的 `c`/`o` 局部别名可以保留；长查询中同一字母指代多类对象导致误读时再改进。`COUNT(o.id)` 与 `COUNT(*)` 在外连接中的区别应按语义核对，不能当作排版互换。

来源核对于 2026-11-16。SQL Style Guide 提供团队可选风格；MySQL 文档决定实际行为。其“30 字节名称”等通用建议及引号偏好不直接变成 MySQL 限制。8.4 文档只能作对应版本参考，旧版本需查其自身行为。

- [SQL Style Guide](https://www.sqlstyle.guide/)
- [MySQL 8.4 标识符大小写](https://dev.mysql.com/doc/refman/8.4/en/identifier-case-sensitivity.html)
- [MySQL 8.4 优化参考](https://dev.mysql.com/doc/refman/8.4/en/optimization.html)
