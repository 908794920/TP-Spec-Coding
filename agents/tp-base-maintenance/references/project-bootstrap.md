# Project Runtime Bootstrap

适用条件：检查或执行项目 Runtime bootstrap 时读取。


本 Skill 继续负责项目 Runtime 初始化健康检查，但它与 Base Binding 迁移是两件事。

- 只读预检：`tp-spec project bootstrap --id <PROJECT> --root <ROOT> --check-only`；
- 未初始化且确认 pristine 时，只有 human_owner 明确要求才执行 bootstrap；
- 非 pristine、ledger/registry 歧义或已有不兼容状态必须 fail-closed，保留 `PROJECT_BOOTSTRAP_UNSAFE`；
- 不得把“去 Junction / 写 project-binding”误当成“初始化项目 Runtime”。
