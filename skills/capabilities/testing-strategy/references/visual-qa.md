# 可视化 QA：Diff-aware 真实浏览器验证

仅在当前工作影响 UI/流程 AC 时读取。本能力不授予浏览器、部署、模型或业务写权限；**真实操作、视觉判断、人工验收分别留证**。从当前 Diff、有效 AC、真实消费页面和已有脚本选择范围，源码字符串断言不能代替页面验收。

## 1. 范围、环境与允许动作

Controller/Router 对应入口，模板/组件对应消费页面，CSS 对应实际引用，API 对应调用流程。已有脚本/数据优先复用；没有可靠影响边界就定向调查或扩展有依据的相关检查，不能盲猜无影响，也不自行全站巡检/完整审批。视口和必要状态以当前 AC 为准，375/430 不是所有项目默认验收义务。

先核对实际部署、地址、获准身份、非敏感数据和 allowed_effects。本地 ChangeSet 不证明服务器已部署；部署未知/过旧时说明边界，不自动部署或拿旧图验新代码。旧任务禁止点击等约束继续有效。等待、权限缺口和未运行不解释为代码缺陷。

已有获准测试账号或受控 storageState 可复用，各角色会话隔离。Mock、test-only Auth Provider 或临时 Patch 不是自动降级选项：仅在明确授权下用于其受限目标，不能证明真实登录、接口或跨系统流转；Visual Manifest 声明 `temporary_bypass_used: true` 并绑定清理 Evidence。密码、Cookie、Token、storageState 不写入共享仓库、AGENTS、Memory、Skill 或未经批准模型输入。

## 2. 稳定路径由上游执行，不另造平台

优先 Playwright Test（TypeScript）及 Midscene 官方 JS/TS 集成；不因 Java 业务栈另造跨语言桥，不并行重写已有 Python/JS 测试。包、浏览器、模型与调用条件在获准环境验证后锁定到项目已有锁文件，保留可回退基线；本能力不安装/升级依赖，不运行 `latest` 或自动下载浏览器。

在**已经配置好且获准**的业务测试项目内，用本地安装的公开 CLI 运行选定文件/用例，例如：

```text
node ./node_modules/@playwright/test/cli.js test <已选测试文件> --grep <已选场景>
```

文件选择和 `--grep` 按上游匹配语义使用，核对实际匹配范围；此命令不代替执行范围审核。配置中的 setup、依赖项目、globalSetup、hooks、webServer 也可能产生额外动作，运行前核对其实际影响；未批准不得让测试启动应用、创建单据或改基线。有业务副作用的测试不盲目自动重试/并发；超时后先按本次业务标识核对是否已提交，不因采集失败重做业务。

复用原配置增加内置 JSON reporter，不重写项目配置。下面仅是最小接入参考，路径/并发策略需与已有获准布局合并，不会由 Base 同步生成：

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  retries: 0, // 有副作用时先确认实际结果，不自动再提交。
  workers: 1,
  outputDir: './test-results',
  reporter: [['line'], ['json', { outputFile: './test-results/playwright.json' }]],
  use: { trace: 'retain-on-failure', video: 'retain-on-failure' },
});
```

稳定填写/点击使用 `getByRole`、label、稳定 id/name 等公开定位与真实对应事件；需要逐字输入、blur 或键盘事件时按实际交互执行。保留可见/启用/遮挡检查，不默认 `force`，不改隐藏值、内部变量或直接调用提交函数绕过被测路径。等待可观察状态，不靠固定长 sleep 或无限重试。

## 3. 画面、动画与真实流转

关键**正常和失败**状态都按 AC 留必要实际截图及对应判读，不只失败采图；用上游 `page.screenshot()` 和 `testInfo.attach()` 关联到用例。图像只是原始材料，生成成功和行为测试通过都不授予视觉 PASS。适用时保存 reference/actual/diff，基线来自获准设计或版本，不自动接受当前图片，也不 mask 被测字段掩盖差异。

静态终态可等待字体、图片及动画稳定；动效专项必须保留真实动画，以短视频/关键帧检查展开收起、连续点击、中途返回等实际过程。相关用例使用上游录制配置保留通过过程，不能只设置失败留视频，不能关闭动画后声称动效通过。无动效要求不全程录制、不让模型通读所有录像。

流程验收使用页面提交与获准角色操作，关联**本次创建的业务标识**、申请人状态、审批待办和获准下一节点。HTTP 200、成功提示、旧单据或确认后取消不是完整流转证据。接口/DB 只在获准时用于隔离数据准备、结果核对和本次自有数据清理，不取代被测页面动作。浏览器移动模拟不代表微信相机、扫码、OAuth、软键盘或 JS-SDK 已实测；真机缺口单列，Airtest 仅在缺口确实需要时再选。

每个 Visual Manifest case 仍绑定真实 AC、route、viewport、actual、report 及当前 `change_set_id`；reference/diff 声明后必须是真实 evidence 内文件。代码变化后旧视觉 PASS 失效，technical-only 不能代替必要视觉/人验。实际 Owner 已按声明范围核验时，human_owner 可通过既有 `task acceptance-override --mode accept --scope visual --ac ...` 留证；该范围必须绑定当前 Subject/ChangeSet，不生成或伪造 Visual Manifest，也不消解无关 blocker。完整门禁、human_owner 的合法 defer/waive 不变，不从报告文本自动编造 Visual Manifest 或 human witness。

## 4. 按需接入 Midscene

只在选定视觉检查点或确有必要的定位/探索处使用官方 `PlaywrightAiFixture`／`PlaywrightAgent`，不是将稳定脚本全部改成 `aiAct`。已有本地工具会看图不证明它有兼容模型 API；先核对接口、模型来源及正确/错误代表画面。没有获准服务就保留视觉待验证，不回退演示/云端默认模型，不建立通用模型网关。

已确认安装、模型及数据发送授权后，项目专用视觉 fixture 可以使用以下公开类型/工厂；不要让普通行为用例导入此文件或自动开启模型：

```ts
import { test as base } from '@playwright/test';
import type { PlayWrightAiFixtureType } from '@midscene/web/playwright';
import { PlaywrightAiFixture } from '@midscene/web/playwright';

export const test = base.extend<PlayWrightAiFixtureType>(
  PlaywrightAiFixture(),
);
```

具体模型配置只保留在受控环境，使用前核实有效配置/端点，不能因未填配置让库默认服务获得授权。公共 Base 不存模型密钥、机器地址或项目身份。所用 API 的探索/重试边界应有实际依据；无法判读保持未知，不删除断言或接受 healer 的 skip 作为成功。

复用官方 `@midscene/web/playwright-reporter` 保存原 HTML；独立文件通过 `checkpoint --collect` 引用，若已在 Playwright attachments 中声明则可用下节受限采集。Base 不解析 HTML 得出 AI 判定，不渲染或自动打开报告，也不创建报告站。外置图片模式需按上游要求另行保全其依赖，不能只复制 HTML 就宣称完整；不自动启动 HTTP 服务。

缓存仅复用上游支持的计划/定位，不代替当前画面判断。`read-only` 仅约束自动缓存写入，不是零模型调用、无副作用或离线执行承诺；cache miss 仍可能调用服务，手动 flush 仍可能写缓存。模型不可用、无法判断、定位失效、认证/环境问题、真实行为失败分开报告，不从一句失败文字自动裁决产品有错。

## 5. 报告、附件与既有 Evidence

使用现有 `checkpoint --result-report <Playwright原生JSON>`，保留原件并自动映射汇总、各项目/重试结果与有限失败定位；可与 JUnit、已登记专业结果引用同批接收。不让模型抄写报告大 JSON。命令、进程退出码、浏览器/视口、模型、真实 actor 和部署主体未被该入口实际观察时保持未知；报告版本是上游声明，不是安装认证。

默认**只接收显式给出的报告本身**，不跟随其中的路径、不下载 URL。需要采集报告声明的本地媒体时增加 `--report-artifact-root <已审核的本次输出目录>`：只读取该目录内明确声明的图片/视频/ZIP/HTML，不递归扫描目录、不解压/执行/渲染，内嵌 body 留在原 JSON 中。不要指定整个项目、HOME 或认证目录；目录授权不是秘密扫描/进程沙箱。原始 JSON/媒体仍可能含日志、身份或表单信息，必须使用获准非敏感输出，摘要不回显任意标题/错误/配置不等于原件已经脱敏。

越界、URL、链接/重解析点、丢失、类型不符或采集中变化会拒绝登记。路径/类型只用于采集限制，不证明文件是真实图像、完整 trace 或正确视觉证据。相对附件路径以显式 root 为基准；原生绝对路径须实际位于该 root，跨机器移动报告时优先恢复获准输出位置，或使用单独显式 `--collect`，不改写旧报告成新主体。Windows 路径在非 Windows 上不猜测转换。

同请求重试只核对已保存报告与媒体，不重跑浏览器、模型或业务；源输出已删除仍可使用完整有效的已入账副本。必要投影失败整批事实不落账，可重建接续失败则事实已提交且返回 PENDING。即使未入账，已发生的外部业务副作用仍不回滚，保留原产物修复采集，不换请求 ID 偷重试提交。

Playwright `expected` 可能包含预期失败，`flaky` 代表重试后结果不同，`skipped`/无执行仍是不完整；接收结果不会压成全通过。多项目的 spec.ok 只是上游合并提示，不代替各项目结果。场景标题、完整错误和 trace 按返回的原件路径/JSON定位定向读取，不能为节省输出丢掉改变结论的失败。

## 6. 项目资产与受控升级

可复用交互脚本保存到对应项目 `.tp-spec/memory/testing/interaction/`，已有 Memory 同类目录优先沿用；适用于业务项目及 TP-Spec 项目自身。项目外已有测试继续原位复用，不为统一目录批量搬迁或复制。公共 Skill 承载方法，AGENTS 与 Memory 索引仅保留短触发和目标链接。Base 同步不创建业务脚本或空测试目录。

### 交互验证到脚本复用
1. 按本次页面/AC 定向读取已有 Memory 导航和相关测试，优先复用或更新；没有索引时只检查已知相关位置，不全盘扫描历史。
2. 在获准环境真实操作；将稳定且有复用价值的流程提炼为脚本，补齐语义定位、业务断言、数据准备及必要清理。录制点击序列或生成代码本身不算验证通过；动效和视觉结论仍需要实际观察证据。
3. 实际回放受影响场景，记录当前对象/版本、命令和结果。环境缺失或未回放标记待验证；可以保存明确标记的候选，不能称为已验证可复用，更不能沿用历史 PASS。
4. 脚本旁的简短说明或文件头记录场景/AC、适用条件、依赖与运行方式、数据及副作用、来源 Task、最近真实回放结果和适用版本；复用现有说明，不每份资产新建一套报告。脚本正文只存一份，Memory 方法和索引链接到它。
5. 本次测试主动评估保存/更新/已覆盖/不保留及原因，在既有测试结果中提供路径，供交付记忆收敛核对。无稳定复用价值不强制留存；重复处理更新原资产，页面变化只处理受影响脚本，失效时标明原因及替代位置。

这些脚本属于明确授权保留的项目长期资产，不登记为临时用例，不在结单清理时删除，也不自动加入 CI 或全量回归。已登记为 Temp 的探索草稿应先将脱敏、整理后的版本保存并读回项目目标，再按 ownership 清理本次草稿，不把 Temp 路径当长期入口。

截图、视频、trace 和运行报告仍归本次 Evidence，Memory 只引用；非敏感可复用夹具可随脚本维护。凭据、Cookie、storageState 和敏感业务数据不得进入共享 Memory，机器路径和环境地址通过运行参数/现有配置提供。找到脚本不产生执行授权，副作用仍受当前任务范围限制。

升级只作为显式维护批次：核对 Release Notes 与依赖/浏览器版本，在隔离环境验证所用登录、条件切换、上传、报告和视觉 API；成功才更新既有锁文件与验证记录，失败保留旧锁及用例。不能用一段配置示例、合成报告或字符串测试宣布工具组合、模型准确性或三流程已验收。

公开接口核验入口（2026-09-08读取；不是已安装/兼容验证证明）：
- [Playwright v1.63.0 JSON reporter](https://github.com/microsoft/playwright/blob/v1.63.0/packages/playwright/src/reporters/json.ts) 与 [公开结果类型](https://github.com/microsoft/playwright/blob/v1.63.0/packages/playwright/types/testReporter.d.ts)。
- [Midscene v1.12.3 包/导出](https://github.com/web-infra-dev/midscene/blob/v1.12.3/packages/web-integration/package.json)、[官方集成](https://midscenejs.com/integrate-with-playwright)、[缓存边界](https://midscenejs.com/caching)。

以上版本仅固定本次源码/文档核验依据；实际运行组合、配套浏览器、模型和项目锁文件仍须在获准环境确认，不宣称所有版本兼容。现有实现没有自研驱动、图像比较、视觉定位、测试 DSL、模型网关或报告引擎。


## 7. 原型 / 交互 / 动效专项
有原型交接时只读取 [原型与交互设计](../../ui-prototype-design/SKILL.md) 的三类清单和当前批准版本，不重复产品设计。按实际受影响交互核对触发、影响区域、完成/取消、失败/重试、重复操作、离开清理和减少动画；动态挂载组件要确认真实公共函数/模块调用，复制资源或同名 CSS 不能证明复用。

响应式检查不通过隐藏必要字段/动作获得通过；输入、值/请求参数、按钮语义和权限行为与当前批准业务一致。将模拟数据、受控时延与评审壳标为原型设施，不能混入产品发布。原型浏览器通过不等于生产流程或权限验收；证据标明 emulated viewport/真实引擎/实际设备，未知真机能力继续待验。普通局部返修只核对受影响点，不固定三轮审批或复做全量原型。
