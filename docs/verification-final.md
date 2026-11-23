# 最终验收｜MRes 对话式蛋白质结构预测

2026-11-21，Asia/Shanghai。按导师任务书第 3、4、8、9 节以及后续允许 ESMFold2 暂用 Mock 的说明验收。**应用、源码、样例、测试和开发总结可以提交。完整考核材料还差由 Kimi 生成并经本人检查的正式 PPTX。** 不需要为提交重跑 GPU 或等候 Biohub 解禁。此处只报告证据，得分由导师评定。

## 按评分项核对

| 项目 | 核对结论 | 直接证据 |
| --- | --- | --- |
| Web 应用 20%（A、B） | React 中英文聊天是提交入口。FastAPI 返回任务编号；后台单并发运行，前端约每两秒读取任务，完成后展示结构。实际浏览器已验证任务切换、旋转、缩放、下载及刷新。 | [本轮浏览器与 HTTP 回执](../examples/outputs/final-rehearsal.json) · [前端任务卡](../frontend/src/JobPanel.tsx) · [后端入口](../backend/app/main.py) |
| 运行时 Agent 25%（C） | 实际 DeepSeek 发出工具调用，按调用 ID 接受回执。已验证提取、追问、沿用同会话已确认序列、换模和查询状态。服务器校验工具参数，限制循环并去重。 | [本轮逐轮工具记录](../examples/outputs/final-rehearsal.json) · [供应商往返探针与真实调试](verification-round-2.md) · [Agent](../backend/app/agent.py) · [会话/去重回归](../backend/tests/test_chat.py) |
| 模型集成 25%（D） | 两个适配器各有显式模式。Protenix Mini 已有聊天触发官方 CLI 的真实 GPU 成功记录。ESMFold2 已接官方接口、真实请求止于 HTTP 451、无真实坐标；成功响应处理使用替身测试。导师允许以已测试的 Mock 验收该流程。 | [Protenix 第六轮](verification-round-6.md) · [ESMFold2 第四轮](verification-round-4.md) · [ESMFold2 适配器](../backend/app/adapters/esmfold2.py) · [Protenix 适配器](../backend/app/adapters/protenix.py) · [1UBQ 来源](../examples/fixtures/README.md) |
| 调试与复现 20%（E） | 非法残基实测拒绝；自动测试覆盖空序列、多 FASTA、未知模型、超时、断连、坏/缺文件、错任务、重启与重复调用。任务记录包括输入、模型/版本、模式、UTC 时间、参数、种子（支持时）、输出或错误。开发总结保留了一次能用测试重现的上下文丢失问题。 | [序列测试](../backend/tests/test_sequences.py) · [任务/输出测试](../backend/tests/test_jobs.py) · [故障页面](../examples/screenshots/round-3-failures.png) · [一页总结](development-summary.pdf) |
| 表达与理解 10% | 按任务书准备了八页文案、8 分钟讲解、操作顺序和问答。本人应能解释一次工具往返、一次调试和一份真实结构的归属。正式 PPTX 与个人现场表现待完成。 | [Kimi 提示词与逐页讲稿](defense-kimi.md) · [面试操作卡](defense-guide.md) |

## 按面试顺序的实际彩排

在本机 Chrome 157 打开**新建的独立回环服务**，使用本轮生产构建、项目原 FastAPI 与真实 DeepSeek 客户端、临时 SQLite 和两个显式 Mock 适配器。测试在聊天框点击发送，使用同一浏览器操作两张卡。会话 `90c5dd8f-4dff-452a-8682-1a1ccc90ec26` 是隔离彩排编号，普通工作台的数据库不包含该会话。可携带的记录含用户原文、UTC、工具回执、任务快照、前端观察与历史归档复核。[本次原始回执](../examples/outputs/final-rehearsal.json)

| 顺序 | 输入或操作 | 实际观察 |
| --- | --- | --- |
| 1 | 中文提交任务书 76 aa 泛素，未选模型 | DeepSeek 尝试调用预测工具，后端返回 `ask_model`，保存序列，任务数为 0。 |
| 2 | 只回复 `ESMFold2` | `predict_structure` 新建 `19823b05-f464-452a-83f5-9ff691ed0b31`，76 aa，Mock。 |
| 3 | `Use the same sequence with Protenix.` | 新建 `7aedad40-fdde-4a61-b4ac-6c74646a1bc1`。SQLite 两条任务记录的完整序列相同；其 SHA-256 为 `233b4b0b8c4616095bc3249f9375fc345d32af7deaef07117d0383c51d6f19aa`。浏览器观察到第二个任务 queued → running → succeeded。 |
| 4 | 用第二个完整 UUID 询问状态 | `get_job_status` 返回该任务 `succeeded (protenix, mock)`，查询没有新增任务。 |
| 5 | 两个任务分别查看、拖动、滚轮缩放、下载，再刷新 | 两个画布的有色像素依次为 253→287→401、250→290→404；旋转同时检验投影形状变化。两份文件各自与对应预览逐字节相同，下载名含模型、mock 和该任务号。查看、下载、刷新期间新增聊天请求数为 0。 |
| 6 | 同一聊天输入 `请用 ESMFold2 预测这条序列：ABCZ123` | `invalid_residues`，显示只接受 20 种标准氨基酸；该轮无工具执行、无新任务。最后恢复出 10 条消息、2 个任务。 |
| 7 | 另开第六轮原 ZIP 的只读浏览器复核 | 原 Protenix Real 任务 `94e78e41-5605-4be1-ae66-8b3f795d818a`。Mac 的画布 353→363→495，实际下载对应 Real PDB，刷新仍为原任务。该结构的计算发生在第六轮，本轮 GPU 推理数为 0。 |

本轮两个新任务都使用公开的 1UBQ 实验坐标。其文件摘要不同，是因为写入了各自的路线与任务 UUID。第六轮真实结构则来自 `protenix==2.0.0` 的 Mini 模型；原始 mmCIF 与导出 PDB 有同一条 76 aa 链、602 个原子。只读校验再次得到 PDB SHA-256 `d879db64ec1b39b93b55ffbb5919f4681ac5a3eb2266baf414865825c9220dd1`。第五轮独立 CLI 归档也通过校验，它有单独的编号。[第六轮原始证据 ZIP](../examples/outputs/round6-protenix-94e78e41-5605-4be1-ae66-8b3f795d818a.zip) · [第五轮范围](verification-round-5.md)

## 其他场景与证据层次

| 要求或边界 | 如何核实 |
| --- | --- |
| 明确模型和序列的一次性请求 | 第四轮直接指定 ESMFold2，走到官方 Real 请求并收到 451；第六轮直接指定 Protenix，走到官方 Real 坐标、Mol* 与下载。两份原始页面分别保留了相应结果。[第四轮](verification-round-4.md) · [第六轮](verification-round-6.md) |
| 缺序列、未知模型、空输入、多个 FASTA、501 aa、模型改写输入 | 本轮 pytest 使用替身检查原文匹配、20 种标准氨基酸、1–500 aa、单条 raw/FASTA、模型白名单；拒绝输入不会执行预测。同会话可复用，跨会话不得复用。[输入用例](../backend/tests/test_sequences.py) · [先给模型及跨会话用例](../backend/tests/test_chat.py) |
| 执行错误、连接失败、超时、缺失或损坏输出 | 本轮 pytest 重跑这些分支。第三轮隔离浏览器分别得到 `execution_error` 和 `invalid_output` 的失败卡；第四轮 451 属于真实平台拒绝。各自的失败不开放下载。[任务测试](../backend/tests/test_jobs.py) · [第三轮](verification-round-3.md) · [第四轮](verification-round-4.md) |
| 结果归属、追溯与重试 | 生成后核验任务目录、蛋白坐标及摘要；读取时再验。跨任务文件、事后篡改或删除、重启遗留任务、重复请求都有回归。真实档中 `input.json`、`job.json`、`events.jsonl`、`provider.jsonl`、`prediction.cif`、`browser.json` 可按 UUID 核对。[worker](../backend/app/jobs.py) · [存储](../backend/app/storage.py) · [归档验证](verification-round-6.md) |

## 复现和交付核验

- 当前工作区执行 `bash scripts/check.sh`，**131 passed**，`tsc --noEmit`、Vite 生产构建和 `pip check` 均通过。Vite 报 Mol* 延迟加载块大于 500 kB，浏览器旋转与下载已在该构建上实际验证。
- 同一台 macOS arm64 上，另取一份不含 `.venv`、`node_modules`、`frontend/dist`、`backend/.env` 和数据库的源码副本。按 README 顺序运行 `setup.sh`、`check.sh`、`pip check` 和第六轮 `verify`，再次得到 **131 passed**、前端构建通过和真实归档校验通过。安装允许使用本机包缓存。第二台机器及其他操作系统未实测。
- 运行 `.venv/bin/python scripts/smoke.py`，当前 8000 直连与 5173 Vite 代理均通过健康检查、空消息 422 和未知会话 404。该命令没有请求 LLM。五轮真实聊天与浏览器交互使用上文的隔离端口。
- 任务书 §8.1 的源码、依赖锁、配置模板、测试、样例结构/截图和 README 均随本地源码 ZIP 提供。§8.2 的开发总结提供可编辑 Markdown 和单页 PDF。§8.3 已按用户安排交付制作稿，由 Kimi 出正式 PPTX。§8.4 的现场操作已经彩排，个人上机前检查见[操作卡](defense-guide.md)。本轮没有修改推理代码、启动 Mac CPU 推理、创建 Colab 自动化或部署公网。
