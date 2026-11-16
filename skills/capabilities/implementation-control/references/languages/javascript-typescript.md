# JavaScript / TypeScript

与[共用标准](../coding-standards.md)一起使用。确认项目运行环境、ES/TS 配置、模块体系和已采用的 ESLint/Prettier 规则；React/Vue 约定以当前项目为准。

- 用含义清楚的变量与函数名，必要时表达单位；保持导出名称、参数顺序和调用语义。具体引号、分号、导入顺序按项目配置。
- 同一表达式叠加业务选择、赋值和调用副作用时，明确各动作顺序并按需要展开。简单条件表达式、可读的数组转换保留惯用形式。
- Promise、事件回调和异步状态变更要能看出谁处理失败、谁拥有后续工作。未经核对不要添加默认 catch、改变拒绝传播或强制等待后台工作。
- 类型应表达实际有效状态；针对会掩盖边界错误的 any、断言或空值处理检查输入与调用者。不要为了表面类型严格引入无法证明的运行时拒绝。
- 注释说明不直观的兼容、事件或生命周期约束；公共 API 文档按已有 JSDoc/TS 类型体系表达。

例如嵌套三元把多个计费档位挤在一行，可展开分支并使用单位明确的参数名；`isMember ? 0 : price` 若已清楚则无需因使用三元而修改。项目允许单引号时，个人偏好双引号不是阻塞依据。

来源核对于 2026-11-16。吸收团队指南中的表达与维护方法；Google 旧 JS 指南已停止更新，TS/JS 指南有 Google 环境限制。模块后缀、框架习惯和全部 lint 预设不自动移植。

- [Airbnb JavaScript](https://github.com/airbnb/javascript)
- [Google TS/JS 指南](https://google.github.io/styleguide/tsguide.html)
- [ESLint 核心概念](https://eslint.org/docs/latest/use/core-concepts/)
