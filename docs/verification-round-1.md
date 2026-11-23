# 第一轮验证记录

日期：2026-11-17（Asia/Shanghai）。测试对象为固定回复通信原型，不是运行时 Agent 或预测任务。

## 已执行

| 检查 | 实际结果 |
| --- | --- |
| 环境检查 | 项目起点仅三份设计文档；默认 Node/npm 不可用，系统 Python 3.9.6；使用现有 bundled Node 24.22.3 / Python 3.12.14 / pnpm 11.25.0 |
| 依赖安装 | 项目新建 `.venv`，安装固定直接依赖并解析运行/开发锁文件；pnpm 安装并生成锁文件。随后实际执行 `bash scripts/setup.sh`，锁文件安装成功 |
| 后端 pytest | **15 passed**；改用 HTTPX ASGITransport 后重新执行，相关 TestClient 弃用警告消失 |
| Python 依赖一致性 | `.venv/bin/python -m pip check`：`No broken requirements found` |
| 前端类型/构建 | `tsc --noEmit && vite build` 成功；Vite 8.3.8，17 个模块，产出 `frontend/dist` |
| shell 脚本语法 | 五个 shell 脚本通过 `bash -n` |
| 真实 HTTP 直连 | `8000/api/health` GET 200，`8000/api/chat` 中英文 POST 200 |
| 真实 Vite 代理 | `5173/api/health` GET 200，`5173/api/chat` 中英文 POST 200 |
| 保存的冒烟脚本 | `.venv/bin/python scripts/smoke.py` 对两个地址均输出 PASS；校验模式、会话编号、固定回复、空任务列表 |
| 浏览器中文/英文 | 实际点击中文示例后发送；输入英文并按 Enter 发送；两次均看到后端固定回复和最近请求成功 |
| 请求中状态 | 页面显示「正在等待后端回复…」，发送按钮显示「发送中…」且禁用 |
| 后端断开 | 停止本任务 Uvicorn 后发送，出现服务不可用说明和重试按钮；没有为失败请求新增助手回复 |
| 恢复后重试 | 重新启动 Uvicorn，手动重试成功；观察到 3 条用户消息、3 条助手消息，未重复添加用户消息，错误提示消失 |
| 15 秒超时 | 暂停本任务 Uvicorn 进程后发送，观察到「请求超过 15 秒未完成」；恢复进程并重试后成功 |
| 刷新行为 | 刷新后聊天记录清空、回到首次请求状态；与本轮页面提示一致，**不代表持久化验收通过** |
| Git 忽略 | `git check-ignore` 验证 backend/frontend `.env`、`.venv`、node_modules、dist、data 路径均被忽略 |
| 资源入口 | Protenix Mini 权重和两个 CCD 文件的 HEAD 请求 200；未下载正文 |

自动测试范围：健康接口的未启用标记、中文/英文/多行普通文本、会话编号回传、空/空白/超长/错误类型/多余字段/错误 UUID/非法 JSON、4000 字符边界。这里的多行文本通过不代表 FASTA 校验已经实现。

## 浏览器证据

- [最终通信页面](../examples/screenshots/round-1-preview.jpg)
- [中英文固定回复](../examples/screenshots/round-1-chat.jpg)
- [后端断开提示](../examples/screenshots/round-1-connection-failure.jpg)
- [请求中与按钮禁用](../examples/screenshots/round-1-request-pending.jpg)
- [15 秒超时](../examples/screenshots/round-1-timeout.jpg)

截图均来自本轮实际运行页面，不是设计稿或模拟图片。浏览器自动化第一次初始化超时，重新检查可用浏览器后成功；上述浏览器结论来自后续实际操作。

## 未执行或尚未实现

- 没有服务端 LLM 配置，未执行真实 LLM 请求、工具调用或工具结果回传。固定回复、HTTP 200、pytest 均不算 Agent 接入。
- ESMFold2 未鉴权、未安装 SDK、未生成或导出结构。
- Protenix 未安装、未执行 CLI help/预测、未下载/加载权重；远程 GPU、Mini 显存与运行耗时未验证。
- 未实现序列规则、工具路由、会话持久化/恢复、后台预测、Real/Mock 工作流、Mol* 或结构下载，不宣称通过相应考核验收。
- 未在另一台干净电脑上复现；本轮是在当前新建项目环境中完成安装，并再次验证锁文件安装命令。
- 未对真实中文输入法组词、所有浏览器/屏幕尺寸做专项人工验收；代码已处理 composition 状态，但不将代码检查等同于输入法实测。

官方文档依据和账户/计算缺口见 [资源核对](resource-check.md)。复现命令见 [README](../README.md)。
