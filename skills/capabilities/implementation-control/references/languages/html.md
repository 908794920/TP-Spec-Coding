# HTML 与模板

与[共用标准](../coding-standards.md)一起使用。先确认原生 HTML、JSX 或 Vue 等模板约定，按实际语法和组件契约判断。

- 结构和命名表达内容与交互含义；优先利用适用的原生元素，核对按钮类型、表单标签及可访问名称。
- 缩进和分组应能读出 DOM 层次；具体属性布局沿用项目 formatter，不按个人喜好重排全部属性。
- 删除包装层、换标签或移动节点前检查 CSS、事件和组件依赖。嵌套较深要指出实际阅读或修改困难，不以固定层数判断失败。
- 关键兼容结构可说明原因；明显标签不需要逐段注释。已有正确的 button、label、替代文本和键盘行为不需要再包一层通用组件。

例如可点击 div 缺少对应键盘行为时指出具体交互缺口；已具备语义和可访问名称的 button 应保留。真实 UI 交互与视觉仍按现有测试规则验证。

来源核对于 2026-11-16。MDN 页主要规范示例，Google 页是团队指南，采纳清晰结构与语义原则，具体省略标签和格式偏好服从项目。

- [Google HTML/CSS](https://google.github.io/styleguide/htmlcssguide.html)
- [MDN HTML 示例指南](https://developer.mozilla.org/en-US/docs/MDN/Writing_guidelines/Code_style_guide/HTML)
