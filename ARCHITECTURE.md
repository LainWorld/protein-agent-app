# ARCHITECTURE — 最小实现决策

> 2026-11-16。产品范围与验收以 `PRD.md` 为准；本文只保留实现时反复需要的约束。

## 1. 技术与部署

```text
React + TypeScript + Vite（聊天、任务卡、Mol*）
  → FastAPI（会话、校验、LLM 工具调用）
  → JobService（后台执行、状态、SQLite）
  → ESMFold2Adapter / ProtenixAdapter（各自 Real 或 Mock）
  → 本地结构文件 → 状态轮询 / 三维查看 / 下载
```

- 一个前端、一个 FastAPI 进程；用 Pydantic 校验、SQLite 保存会话/任务、文件目录保存结构与执行记录。暂不引入 Agent 框架、Redis、Celery、向量数据库或 WebSocket。
- 默认本地运行，前端开发服务器代理 `/api`。若获得远端 GPU，优先将后端与 Protenix 放在该机，经 SSH 端口转发访问，不新增推理微服务。
- LLM 优先使用免费额度或实验室服务；不足时可购买 DeepSeek 或小米 MiMo API。先核对所选模型的官方工具调用协议并实测，再选定一家接入；供应商与模型尚未确定。只封装一个薄 `llm_client`，不建设多供应商切换系统。

## 2. Agent 与会话

只提供两个工具：

```text
predict_structure(sequence, model: "esmfold2" | "protenix") → job_id, status, mode
get_job_status(job_id) → status, model, mode, result_available, error
```

- LLM 负责理解与提出工具调用；后端负责校验、执行和真实状态。工具返回提交回执，不能同步等待整个预测。
- `conversation_id` 由后端生成；保存消息、待补充序列、最近确认序列和最近任务 ID。给 LLM 最近必要消息及这些上下文，不做长期记忆或自动摘要。
- 缺参数先追问；“同一序列”只引用本会话确认过的序列；状态查询默认指向本会话最近任务，歧义时追问。
- 序列只允许去空白、转大写、去单条 FASTA 标题；保留非法字符供校验报错。工具参数须与本轮提供的序列或已确认历史一致，防止 LLM 删改序列。MVP 接受 20 种标准氨基酸，非空，上限暂定 500 aa；真实适配器再校验其限制。此上限是应用选择。
- 工具调用和结果按供应商协议配对回传 LLM；限制循环次数，同一次工具调用不重复创建任务。拒绝未知工具/模型；不执行 LLM 生成的命令或文件路径。
- 状态文字、结果链接与 Real/Mock 标记由后端数据生成；LLM 不得自行宣布成功。轮询不调用 LLM；LLM 不可用时明确报错，不用关键词脚本冒充 Agent。

## 3. API、任务与存储

| 接口 | 最小职责 |
| --- | --- |
| `POST /api/chat` | 输入 `message, conversation_id?`；返回会话 ID、助手消息、关联任务 ID |
| `GET /api/conversations/{id}` | 恢复本会话消息及任务卡片 |
| `GET /api/jobs/{id}` | 返回状态、模式、模型/版本、时间、错误和结果可用性 |
| `GET /api/jobs/{id}/structure` | 按任务读取 PDB/mmCIF，供查看与下载；未成功或文件无效时拒绝 |

预测入口只通过 Agent 调用 JobService，先不增加重复的 `/api/predict`。前端约每 2 秒轮询非终态任务，终态停止；网络断开显示连接问题，不自行改写任务状态。

- 正常状态为 `queued → running → succeeded | failed`；排队中被中断也可进入 `failed`，校验失败不入队。使用简单后台任务并限制推理并发为 1；同步 SDK 在线程执行，Protenix 在独立子进程执行，均设超时。
- SQLite 中的 Job 保存：`id, conversation_id, sequence, model, model_version, mode, status, created_at, started_at, finished_at, parameters, seed?, output_path?, error?`。时间统一 UTC；界面转换为本地时间。
- 每个任务使用 `data/jobs/<job_id>/` 独立目录；记录实际配置、工具调用与执行日志。原子更新状态，验证文件存在、非空、可解析且含蛋白质坐标后才能标为成功；不只检查扩展名。
- 一个后端服务进程，不使用多 worker。重启时将遗留的排队/运行任务标为失败并说明中断；不承诺断点续跑、不自动重新提交。前端刷新可恢复会话和既有结果。
- 错误使用稳定代码和简短说明；密钥只在服务端环境变量中，日志脱敏。下载路径从任务记录取得，不接受用户指定磁盘路径。

## 4. 两个模型的接入边界

共用内部接口：`adapter.predict(sequence, output_dir, options) → StructureResult(path, format, model_version, parameters, seed?)`；业务层负责任务状态，适配器负责模型输入、执行与输出转换。

| 适配器 | 真实接入方案 | 前置验证 |
| --- | --- | --- |
| ESMFold2 | 官方 Biohub API/SDK；先验证短序列请求与结构导出，再接入后台任务。不得用旧 ESMFold 替代 | 可用账户/额度、准确模型 ID、输入限制、响应格式、超时处理 |
| Protenix | 官方 Python 包/CLI；生成单个 `proteinChain`、`count=1` 的 JSON，在独立环境执行并收集 mmCIF。优先试官方 Mini 变体，关闭 MSA/模板，记录实际变体与种子 | GPU/运行环境、权重与依赖、锁定版本的 CLI 参数、短序列输出 |

Protenix 子进程使用参数列表而非拼接 shell。关闭 MSA/模板符合本项目范围，但会限制科学质量；不做精度承诺。实际模型 ID、版本和参数在首个真实样例通过后固定到配置与依赖锁文件；未提供的版本/种子注明未知或不支持，不猜测。

两个模型分别配置 `real/mock`，允许一个真实、一个模拟。Mock 复制有来源说明的固定示例结构，记录 fixture ID，页面明确其并非输入序列的预测；下载文件名包含 `mock`。Real 失败只报失败，切换 Mock 必须显式配置并创建新任务。

当前未验证任何外部资源。开工先做 LLM、ESMFold2、Protenix 三个最小探针；额度、模型权重可访问性和计算资源以实际结果为准。ChatGPT 会员不等于已经配置好 API：先核对可用免费资源，必要时采用上述付费 LLM API；预测 API/GPU 仍优先免费或实验室资源。LLM API 用于对话与工具调用，不能替代两个预测模型的算力或访问权限。无 LLM 资源时，该验收项保持未完成。

## 5. 目录与验证

```text
frontend/src/        # Chat、JobCard、StructureViewer、API 请求
backend/app/         # main、schemas、agent、llm_client、jobs、storage
backend/app/adapters/# esmfold2、protenix、mock 与共用接口
backend/tests/      # 校验、工具路由、任务与适配器契约
examples/           # 演示序列、Mock 结构及来源
data/               # SQLite、任务文件；不提交版本库
```

用 pytest 覆盖非法输入、模型路由、缺参数/上下文、真实状态、执行错误、坏文件、Mock 标记与任务隔离；常规测试使用可控替身，不消耗外部额度。另做真实 LLM 的基本预测/追问/换模型联调；真实模型逐个做短序列冒烟测试，清楚标出未执行项。浏览器人工验收三维加载、下载、轮询及故障展示；前端构建和类型检查通过。

依赖与配置固定后写入 README 和 `.env.example`；本文件不保存安装教程或调试流水账。新增组件只有在当前方案不能满足 PRD 验收时才引入。

接入时参考官方资料（本次核对：2026-11-16）：[ESMFold2](https://www.biohub.ai/models/esmfold2)、[Protenix 推理](https://github.com/bytedance/Protenix/blob/main/docs/training_inference_instructions.md)、[Protenix 变体](https://github.com/bytedance/Protenix/blob/main/docs/supported_models.md)、[输入格式](https://github.com/bytedance/Protenix/blob/main/docs/infer_json_format.md)、[Mol*](https://molstar.org/)、[ChatGPT 套餐 API 额度说明](https://developers.openai.com/api/docs/guides/chatgpt-api-credits)。
