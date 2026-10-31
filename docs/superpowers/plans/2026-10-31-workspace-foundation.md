# 公司空间与基础业务实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans，在当前 worktree 按任务执行，用户已选择当前会话内实施。

**目标：** 完成全业务迁移的前两个阶段，让开放注册账号拥有独立空间，并能在网页管理公司资料和客户。

**架构：** SQLite 统一事务管理账号、默认空间和公司资料；请求依赖从签名会话查出空间，所有业务 SQL 都带空间条件。客户字段对应原业务需求，独立实现，不加载原业务运行时。

**技术栈：** Python、FastAPI、SQLite、Pydantic 2、原生 HTML/CSS/JavaScript、pytest。

## 共同约束

- 沿用已确认的多租户设计；每个账号一个默认空间和默认公司。
- 原本的账号数据库原位升级，旧演示账号密码和登录能力保留；不导入原业务数据库。
- 用户与空间 ID 来自会话和数据库；拒绝表单中伪造的归属字段。
- 全业务迁移仍按六阶段推进；本计划实现阶段一、二的基础闭环，其余阶段保持待完成状态。
- 不修改原项目业务及授权模块。

## 任务 1：事务迁移与身份上下文

文件：新增 `login-demo/database.py`、`tenancy.py`、`tests/test_tenancy.py`、`pytest.ini`，修改 `auth.py`、`app.py`。

接口：`database.connection(path)` 提供启用外键、提交/回滚并关闭连接的上下文；`database.migrate(path)` 原子且幂等；`tenancy.require_tenant(request)` 返回不可变的 `TenantContext(user_id, workspace_id, email)`；`GET /api/workspace` 返回当前空间。

- [ ] 测试旧 accounts 数据库升级两次只创建一个空间、注册同时创建空间、重复注册不会遗留空间、外键实际开启。
- [ ] 测试未登录返回 401、两账号返回不同空间、伪造空间 header/query 不能改变归属。
- [ ] 执行失败测试：`python -m pytest -c login-demo/pytest.ini login-demo/tests/test_tenancy.py -q`。
- [ ] 实现事务迁移、原子注册和认证请求依赖，再执行上述测试与现有认证测试。

## 任务 2：公司资料与客户 API

文件：新增 `login-demo/business.py`、`business_api.py`、`tests/test_business_api.py`。

接口：`GET/PUT /api/company`；`GET/POST /api/customers`；`GET/PUT/DELETE /api/customers/{id}`；客户筛选 `q`、`tier`、`country`；`GET /api/customers/export`；`POST /api/customers/import` 接收 UTF-8 CSV 内容。客户的联系人、分级、国家、来源、社交资料等字段与原业务对应。

- [ ] 写测试：两账号各自创建同名客户、列表和搜索独立；另一账号对目标 ID 的 GET/PUT/DELETE 都是 404；公司编辑仅影响本空间。
- [ ] 写测试：body 内 `user_id/workspace_id/company_id` 被拒绝；空姓名、错误等级/评分校验失败；CSV 导出与导入不跨空间，导入失败无部分写入。
- [ ] 运行测试，确认缺少路由导致失败。
- [ ] 通过参数化 SQL 和固定字段白名单实现 repository 与 API，测试转绿。

## 任务 3：中文业务界面与运行验证

文件：修改 `login-demo/static/index.html`、`app.js`、`app.css`、`README.md`；新增 `business.js` 和浏览器验证脚本。

- [ ] 接入工作台导航、公司资料表单、客户搜索/分级筛选、客户添加/编辑/删除、CSV 导入导出、中文错误与操作反馈。
- [ ] 会话失效/退出后清空全部业务界面及表单缓存；异步结果不能写回其他账号的新页面。
- [ ] 用 API 隔离测试和真实浏览器流程验证注册、保存公司、新建编辑客户、退出换账号、空列表、刷新还原会话。
- [ ] 执行全套独立测试、JS 语法、Python 编译、Git whitespace 检查。
- [ ] 启动更新后的演示服务，保留分支供预览；明确剩余业务迁移阶段。

## 进度

本计划任务 1–3 已完成：实现了默认空间、旧账号升级、公司资料、客户管理及 CSV；40 项独立测试通过。真实浏览器验证了登录、客户新增/编辑/搜索、公司资料保存、刷新恢复、退出换号隔离及 CSV 实际下载。

阶段 3（AI/对话/记忆）、阶段 4（订单/文档/图纸）、阶段 5（自动化与外部能力）、阶段 6（完整工作台复刻）尚待迁移，不计作本计划已完成。公司当前为每个账号一个默认公司资料，不提供多公司切换或团队成员。
