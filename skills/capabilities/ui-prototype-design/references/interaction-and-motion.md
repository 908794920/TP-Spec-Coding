# 交互与动效：状态、取消与响应式

> 修改/适配自 Impeccable `reference/operate.md`、`animate.md`、`adapt.md`，commit `f2c7051853848826aac2f4646581d62a732155ad`，Copyright 2025 Paul Bakaus，Apache-2.0。此文件按 TP-Spec 需求重新组织，非原文翻译/完整分发；[许可和改动说明](../../../../THIRD_PARTY_NOTICES.md#p1-视觉方法适配)。

## When
原型或产品涉及加载、提交反馈、展开/收起、导航/浮层、重复点击或中断时读取；不要为了调用本方法让静态页面新增动效。

## Steps
为每个实际交互写明“触发 → 影响区域 → 过程 → 成功/失败/重试 → 结束/取消”；明确已有状态和可打断关系。组件状态覆盖适用的默认、hover/focus、active/disabled、loading、error/success，不能只画正常终态。

- 动效解释状态、空间关系或操作反馈，不让使用者等待入场表演；时长/easing 沿用产品规范，不将上游推荐毫秒数变为强制阈值。
- 加载始于真实请求/操作，局部请求不无条件遮全页；完成、失败、取消都结束加载，重复操作遵循已批准语义而非自行加新限流。
- 请求取消与结果忽略分开：依据现有 API 取消可取消的请求；迟到结果不能写入已离开的视图。卸载/离开清理该实例的 timer、listener、animation 和 loading，不动其他 Work/视图的资源。
- 失败保留合法输入、解释已知原因、提供可达重试；成功与取消反馈不依赖 animationend，也不以 HTTP 200 或 Toast 假装后续业务流已完成。
- 优先现有 CSS transition/keyframes、Web Animations API 或已有库，不为简单效果新增依赖。性能判断来自实际测量，不能因使用 transform 就宣称流畅；无必要不 animate 布局尺寸，不永久挂 will-change。
- `prefers-reduced-motion` 下减弱/取消非必要位移与循环，但保留加载/错误/完成文本、焦点和状态反馈；默认内容可见，脚本/动画失败不隐藏必要内容。
- 响应式依内容与输入能力调整，不照搬设备名单或固定断点。保留信息架构和核心操作，触摸路径不依赖 hover，浮层不被 overflow 裁剪，滚动和控件手势不互相劫持。

## Verify
实际执行正常、失败、重试、连续操作、中途取消/返回和离开后恢复；核对没有残留遮罩/监听/计时器、重复提交或过期结果。目标宽/窄视口与键盘路径成组检查；有真实手势则操作到完成，截图不证明手势。

记录正常动效关键帧/短过程，以及 reduced-motion 下仍能理解的状态；不能全程关闭动画后声称动效通过。区分 Chromium 模拟视口、合成触控与真实设备；没有目标硬件时列明缺口，不把它变成不交付其他已验证部分的理由。证据使用既有 [Visual QA](../../testing-strategy/references/visual-qa.md)，无需上游自动 Hook 或独立引擎。
