# 小系统组件消费示例

**以下为假设项目的表达示例，文件、函数、路由、版本与 AC 名称均不是本仓真实资产，代码没有执行，验证状态为 `NOT_TESTED`。** 采用时替换为当前项目已读取的真实实现、实际参数和输出位置，不照搬示例业务或新建同名文件。本例假设现有保存动作已约定处理中不重复提交；组件说明不产生这项业务规则。

## 一处有效入口

假设项目已有 `prototype/design.html` 作为 effective 设计入口，源码版本记为 `demo-v1 / 当前源码快照待采集`。入口展示当前范围、组件目录、代表组合、证据与待验项；README 仅链接该入口。目录使用名称锚点即可：

| 名称 | 规格/预览定位 | 实际实现与页面消费（假设路径） |
|---|---|---|
| 操作按钮 Button | `design.html#button` → 本组件参数、成组状态、调用示例 | `js/ui.js#renderButton` → `js/editor.js#renderSaveAction` |

## Button 的实现和消费条目

假设已读取的 `js/ui.js#renderButton` 如下，`esc` 是项目既有 HTML 转义函数：

```js
function renderButton({ label, variant = 'primary', disabled = false, busy = false }) {
  return `<button type="button" class="btn btn-${esc(variant)}"
    ${disabled || busy ? 'disabled' : ''} ${busy ? 'aria-busy="true"' : ''}>
    ${esc(label)}${busy ? '（处理中）' : ''}
  </button>`;
}
```

| 参数/输出 | 来自该签名的真实约定（假设实现） |
|---|---|
| `label: string` | 无默认值；调用方传可读动作名，长标签换行 |
| `variant: string = 'primary'` | 当前 CSS 只有 `primary`、`secondary` 两个展示变体；这是支持范围说明，不额外给业务输入添加拒绝规则 |
| `disabled: boolean = false` | 原生禁用；不可用原因由现有页面附近的说明给出 |
| `busy: boolean = false` | 显示处理文字、`aria-busy`，禁重复激活；标签仍由调用方提供 |
| 返回 `string` | 按钮 HTML；本函数不提交数据、不注册点击回调，行为由页面绑定；原生 Enter/Space 激活沿用浏览器 |

假设已读取的 `css/ui.css` 中，`.btn` 消费 `--font-body`、`--radius-control`、`--space-control-x`；`.btn-primary` 消费 `--action-bg`/`--action-text`，`.btn-secondary` 消费 `--surface`/`--border`/`--text`。这些变量定义在 `css/tokens.css`。本组件没有图标/外部素材，资产消费为不适用；来源是项目已有原生按钮模板，无新增依赖。

假设页面 `js/editor.js#renderSaveAction` 的实际调用已定位：

```js
const actionHtml = renderButton({ label: '保存设置', busy: view.saving });
```

在真实工件中，源码/调用定位应链接项目实际文件及符号、有效行号或已有源码查看入口。源码只提供函数名却没有调用点时，标为待核对，不能宣称页面已消费。

## 状态成组与代表组合

| 状态 | `design.html#button` 的可操作预览 | 页面/组合与验证状态 |
|---|---|---|
| 默认与变体 | 并列 primary/secondary；真实点击显示现有反馈 | `editor.html` 正常保存入口；`NOT_TESTED` |
| 长标签/窄屏、焦点/按下 | 长标签、Tab 和 Enter/Space，核对可见焦点及触控范围 | 编辑表单与固定操作区组合；`NOT_TESTED` |
| 禁用 | `disabled: true`，旁边标演示不可用原因 | 页面真实禁用条件沿字段/动作清单；`NOT_TESTED` |
| 局部加载与结束 | 既有获准模拟保存触发 `busy: true`，结束恢复 | 页面既有 `view.saving` 状态；模拟，`NOT_TESTED` |
| 失败/恢复、成功 | 在代表表单中演示失败保留输入、重试与成功反馈 | 反馈由页面已有字段/提示组件承担，Button 没有 error/success 参数；`NOT_TESTED` |
| 选中 | 不适用：本例是操作按钮，无切换值语义 | 不新增 pressed/selected API |

假设代表组合是 `editor.html`：已有字段 → Button 保存 → 原有局部反馈/失败恢复 → 返回。入口按本次受影响清单链接字段/动作 `保存`、请求/加载 `保存设置` 及已有对应 AC；不在此重写必填、权限或保存参数。预览可沿用该页面，分组状态入口指向具体组件和组合，无需另建调试平台。

验证导航指向任务既有 Evidence。实际运行后填浏览器、视口/输入方式、源码快照、预期/实际及证据；未执行继续 `NOT_TESTED`，本例不提供虚构结果。版本更改后核对旧证据适用性，不把上次通过自动带到新实现。

下游 AI 依次读：有效入口范围/版本 → Button 规格与状态 → token/源码及 `renderSaveAction` 调用点 → 代表组合及三类清单 → 编写本页差异并验证。其他实际使用组件按相同粒度登记，范围只限当前代表路径所需。此顺序用于真正复用当前组件，不要求把示例目录或字段结构变成固定框架。
