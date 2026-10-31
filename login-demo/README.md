# Workroom 外贸工作台演示版

本地运行的独立演示应用，支持开放注册、邮箱密码登录和隔离的公司空间。所有代码位于本目录，不导入原项目 `trade` 包，不修改原应用的试用或激活逻辑。

目前已接入：

- 账号注册、登录、退出、刷新恢复登录状态。
- 一个账号一个默认公司空间；旧演示账号启动后自动补齐空间。
- 公司名称、官网、联系人、地址、行业、主营产品、目标市场、助手身份设定。
- 客户新增、编辑、删除；联系人、国家、分级、邮箱、社交联系方式、主营品类和跟进备注。
- 客户搜索、国家和等级筛选、分页。
- UTF-8 CSV 客户导入和导出。导入最多 1000 行、文件最多 2 MB，表头必须包含 `name`；可先导出空列表作为模板。错误文件整体拒绝，不留下半份数据。

完整业务迁移尚未完成：AI 对话/记忆、订单/文档、定时任务/OSINT 等仍待接入，当前界面仅展示已经可用的功能。

## Windows 启动

在本目录运行（需要可用的 Python 3.11+）：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
uvicorn app:app --reload
```

默认地址为 `http://127.0.0.1:8000`。本次演示使用 `8017` 端口；可用下列命令启动同一地址：

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8017
```

如果系统 `python` 只是 Windows Store 别名，可在这台电脑使用已安装的 Anaconda：

```powershell
& 'C:\Users\wangdiao\anaconda3\python.exe' -m uvicorn app:app --host 127.0.0.1 --port 8017
```

## macOS / Linux 启动

在本目录运行：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn app:app --reload
```

## 测试

```sh
python -m pytest tests -q
```

从仓库根目录运行时，使用 `python -m pytest -c login-demo/pytest.ini login-demo/tests -q`，避免继承原项目的测试配置。

## 数据和隔离

账号、默认空间、公司资料和客户保存在本应用目录下的 `data/accounts.sqlite3`，与运行命令时的当前目录无关。密码使用带随机盐的 PBKDF2 哈希保存。

请求通过签名 Cookie 中的用户 ID 解析空间。业务接口不接受客户端指定归属；客户的读取、修改、删除、列表和 CSV 导入导出全部受空间条件限制。数据库外键还会拦截客户与其他空间公司之间的错误关联。

已有登录演示数据库会原位升级，不导入原项目的业务数据。此次升级前的本地备份位于 `data/accounts-before-workspaces.sqlite3`（仅本机保留，不提交到 Git）。

可设置 `LOGIN_DEMO_SECRET` 以保持服务重启后的会话有效。未设置时，每次进程启动都会生成新密钥，旧会话失效，需要重新登录；账号和业务记录继续保留。

应用当前用于本地演示，启动时只监听 `127.0.0.1`。公网部署和团队协作尚未纳入当前实现。
