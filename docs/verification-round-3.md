# 第三轮验收：真实对话、两个 Mock 任务

2026-11-19（Asia/Shanghai）。输入为 76 aa 泛素；结构样例为[固定的 RCSB PDB 1UBQ 文件](../examples/fixtures/README.md)。这里的“成功”仅指 Mock 任务成功生成并校验示例文件。真实 ESMFold2 / Protenix 推理次数均为 **0**。

## 实际应用、真实 LLM

`scripts/smoke.py --live` 从 Vite 代理进入 FastAPI。第一轮只发序列，实际收到选模追问、没有任务；第二轮回复 ESMFold2、第三轮改用 Protenix，同会话先后产生两个真实 DeepSeek `predict_structure` 调用。第四轮用第二个任务 UUID 查询，实际收到 `get_job_status` 和数据库的 `succeeded`、`mock`。复读 SQLite 工具日志，前述三次调用均未标为重放。该会话 `6214c45e-de83-4b44-9d01-833dff28d6d6` 恢复出 8 条消息、2 个任务。

| Mock 路线 | 任务 UUID | 开始 → 完成（UTC） | 文件 SHA-256 |
| --- | --- | --- | --- |
| ESMFold2 | `363a83d0-d93d-41bf-ab43-5dd12c8e6a72` | 07:49:57 → 07:50:00 | `7d0bb5fab0ffabccc2800d863444239f563cd3c96c681d07f40fed02de15eabd` |
| Protenix | `762c207f-8400-4550-947b-b5ec739e0d72` | 07:50:03 → 07:50:06 | `007c509a2ca72180726f98cc77f39a894eac46407165b89e1b79ccf5eacd7b1b` |

两个请求中的完整 76 aa 均由后端与用户原文/确认历史比对。两个 GET 轮询均观察到 `running → succeeded`；这些 HTTP 检查没有采样到短暂的 queued。离线并发测试让第一个任务暂时停在执行中，观察到第一个 running、第二个 queued，两者均无下载，释放后依次成功，执行峰值为 1。

每份输出为 78,742 字节，坐标相同；区别在标记路线和任务 ID 的 REMARK，因此摘要不同。两次均逐字节比对查看接口和下载接口、独立计算摘要并核对数据库。留存文件：[ESMFold2 Mock PDB](../examples/outputs/esmfold2-mock-363a83d0-d93d-41bf-ab43-5dd12c8e6a72.pdb)、[Protenix Mock PDB](../examples/outputs/protenix-mock-762c207f-8400-4550-947b-b5ec739e0d72.pdb)。每次新跑会有新 UUID / 摘要；历史文件不是新推理。

## 浏览器与失败检查

- Chrome + Playwright 使用真实 Mol* 5.13.1 WebGL 画布（浏览器测试启用 SwiftShader）。分别打开两张卡，检查出现非空彩色结构，真实拖动、滚轮缩放并比对投影像素；实际下载文件名带对应模型、`mock` 和 UUID，下载字节的摘要等于该任务的服务端记录。切换后只保留一个画布。刷新能恢复两张卡；浏览器对该已验收会话的查看、下载与刷新没有发起聊天请求。[ESMFold2 截图](../examples/screenshots/round-3-esmfold2.png) · [Protenix 截图](../examples/screenshots/round-3-protenix.png)
- 在**独立临时数据库**中通过聊天提交两条确定性故障样例。仅替换 LLM 上游与故障适配器；实际使用同一套队列、校验、API、React 任务卡及浏览器。ESMFold2 注入执行异常得到 `execution_error`；Protenix 写出仅标记和 END 的 PDB，得到 `invalid_output`。每张卡实际从运行中经约两秒一次的轮询变为失败，均没有成功标记、查看按钮、下载按钮或画布；刷新后两条错误仍在。[失败截图](../examples/screenshots/round-3-failures.png)
- pytest 还覆盖执行超时、坏/空/缺失文件、只有水坐标、输出归属、篡改/删除成功结果后撤销可用性、重启标记失败、Real 不降级、HTTP 重试与工具调用去重、上游在工具回传后失败不落孤立任务。实际与替身验证的分界见[运行说明](../README.md)。

## 环境和范围

现有 macOS arm64 / Python 3.12.14 / Node 24.22.3 / pnpm 11.25.0。已实际运行锁文件安装、`pip check`、83 项 pytest、TypeScript 和 Vite 生产构建。Mol* 为按需加载的大块依赖，构建有体积提示，不妨碍完成。未在第二台干净电脑、多种显卡或所有浏览器上重测；不把 WebGL 可视化当作科学准确性验证。没有下载大型权重、安装预测软件或调用收费预测服务。设计文档保持原样。
