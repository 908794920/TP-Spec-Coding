# CSS

与[共用标准](../coding-standards.md)一起使用。先确认 BEM、CSS Modules、组件作用域、工具类或其他项目既有体系。

- 类名表达组件、状态或用途，沿用已有命名体系；修改类名时检查模板和脚本消费者。
- 选择器作用范围、层叠和覆盖来源应可追踪。检查本次新增的互相覆盖、重复声明、过强选择器及隐含布局依赖。
- 声明顺序、缩进与换行沿用配置；涉及布局意图、兼容性或必要覆盖时说明原因。
- 数值、token、响应式断点结合现有设计与实际复用判断；不把每个独立数值都强制抽成变量，也不为统一样式扩大改动。

`!important` 要核对原因及影响，例如有说明的第三方遗留覆盖可以成立。只有多处叠加导致样式来源难定位时，才提出针对覆盖链的修复；BEM 与 CSS Modules 均可合理使用。

来源核对于 2026-11-16。采用清晰命名、格式和结构原则，Google/MDN 的示例偏好不替代项目样式体系。

- [Google HTML/CSS](https://google.github.io/styleguide/htmlcssguide.html)
- [MDN CSS 示例指南](https://developer.mozilla.org/en-US/docs/MDN/Writing_guidelines/Code_style_guide/CSS)
