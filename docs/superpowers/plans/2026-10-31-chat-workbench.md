# AI 对话工作台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans，沿用当前 worktree 和当前会话执行。

**目标：** 接通真实模型的流式对话，按空间保存会话、模型设置和用户维护的记忆备注。

**架构：** 新增独立 conversation/message/settings/memory 数据表；所有查询经登录空间依赖过滤。使用 HTTPX 调用兼容聊天接口、SSE 向浏览器输出；API Key 经本地持久密钥加密保存。配置不依赖原项目或其凭据。

**技术栈：** FastAPI、SQLite、HTTPX、cryptography Fernet、原生 JavaScript。

## 共同约束

- 测试使用 HTTPX MockTransport，测试时不调用外部付费模型。
- 无模型密钥时返回可读的配置错误；模型失败和断连不得显示完成状态。
- 对话、记忆、模型设置和绑定客户都只能访问当前空间。
- 请求可选择普通助手、开发信、跟进和客户分析写作模式；客户分析在没有搜索工具时不得声称做过在线验证。
- 这一阶段接入对话闭环；原项目的 Hermes 工具执行、自动联网、向量记忆和完整技能包不计作已迁移。

## 任务

- [ ] 先写失败测试：模型设置不回传密钥、数据库不存明文、空间隔离、跨空间客户绑定 404。
- [ ] 增加表结构和仓储；提供会话 CRUD、记忆 GET/PUT、设置 GET/PUT。
- [ ] 先写失败测试：SSE 按 delta/done 输出、失败/截断输出 error、未配置时不创建消息、同会话并发 409、历史按空间隔离。
- [ ] 实现模型流和取消处理，把公司资料、客户资料、记忆和模式提示词注入当前对话上下文。
- [ ] 加入 AI 工作台、会话列表、模式选择、停止生成、设置和记忆页面。所有动态文本用 textContent 渲染；退出时取消流并清空页面。
- [ ] 运行全部独立测试、Python/JS 语法检查和实际浏览器流程；运行时保留现有 8017 预览地址。

## 验证进度

已实现上述代码与 UI。新增模型测试覆盖密钥不回显、持久加密、租户绑定、会话历史、错误/截断流、同对话并发和取消后新回合的保护。真实浏览器验证了 AI 工作台入口、关联客户、未配置 Key 提示和记忆备注保存。外部模型请求由测试替身验证，未使用真实 API Key，不将这项结果计作真实模型连通性验证。

订单、文档、自动化、在线搜索、Hermes 工具和完整技能包仍属后续迁移范围。

## 文件

新增：`login-demo/chat_store.py`、`chat_api.py`、`model_gateway.py`、`secret_store.py`、`tests/test_chat_api.py`、`static/chat.js`。

修改：`database.py`、`app.py`、`requirements.txt`、`static/index.html`、`static/business.js`、`static/app.css`、`README.md`。
