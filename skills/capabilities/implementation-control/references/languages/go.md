# Go

与[共用标准](../coding-standards.md)一起使用。确认 Go 版本、模块和项目约定；采用适用的 gofmt 格式，已格式化代码不因个人偏好反复重排。

- 名称符合导出语义和包上下文。短接收者名、紧邻使用的局部变量属于常见惯例；跨较大范围或含业务含义时使用足够明确的名字。
- 对导出 API 按项目与 Go 文档习惯说明用途、使用约束和必要的并发/所有权信息；避免只是复述名字。
- error 返回、包装与处理应保留调用者需要的语义；不要吞错、重复处理同一错误或以 panic 代替普通错误契约。
- 修改 goroutine、channel、context 或 defer 时明确结束、取消和资源释放责任；对应真实调用判断，不能给所有函数机械增加 context。
- 保留简单惯用控制流；接口和抽象由实际消费者需要驱动。nil 与空切片的差异涉及序列化时，应核对契约。

例如 `(c *Client)` 作为短方法的接收者名无需扩写；导出方法重命名会影响消费者，不能以命名更完整为由直接修改。

来源核对于 2026-11-16。Go Code Review Comments 为主要审查参考；Effective Go 明确不积极更新，泛型和后续语言特性查对应版本文档。

- [Go Code Review Comments](https://go.dev/wiki/CodeReviewComments)
- [Effective Go](https://go.dev/doc/effective_go)
