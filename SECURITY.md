# Security Policy

## Supported Version

安全修复优先针对当前公开活动版本。历史版本仅在问题能够无风险回移时考虑修复。

## Reporting a Vulnerability

请不要在公开 Issue 中提交可直接利用的漏洞细节、真实凭据、生产数据或用户隐私信息。

优先使用 GitHub 仓库 **Security** 页面提供的私密漏洞报告能力（如果仓库已启用）。如果当前仓库尚未启用私密报告，请创建一个不包含 exploit/secret 的最小公开 Issue，请维护者提供私密联系方式，再单独发送完整细节。

报告建议包含：

- 受影响版本 / commit；
- 攻击前提；
- 最小复现步骤；
- 影响范围；
- 是否涉及 Runtime 账本、路径解析、生产授权、敏感数据或供应链；
- 可行的缓解方式（如果已知）。

## Sensitive Data

提交 Issue、日志、测试数据或 PR 前，请移除：

- API Key、Token、Cookie、证书和账号凭据；
- 真实手机号、身份证、邮箱等个人信息；
- 内网地址和生产数据库连接信息；
- 用户机器绝对路径中可能泄露身份的信息；
- 项目 Runtime DB、真实 Task evidence、私有 Wiki/Knowledge 数据。

## Security Boundaries

TP-Spec-Coding 的核心安全原则包括：

- 无法确定路径/项目身份时 fail-closed；
- 生产写、DML/DDL 与高风险授权必须显式确认；
- 验证 PASS 必须有真实 evidence；
- Orchestrator 不代替专业角色伪造账本归属；
- 公共仓库不应包含机器级 registry 或用户运行数据。
