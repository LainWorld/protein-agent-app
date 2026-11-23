# 第二轮实测 · DeepSeek 运行时和会话恢复

2026-11-19，macOS arm64。本轮只验收到**真实 LLM 提出工具调用、后端核对参数、回传结果并恢复对话**。实际预测任务数：0；实际结构输出：0。

## 供应商：文档与调用分开记录

- **文档确认：** [DeepSeek 模型表](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)、[模型列表接口](https://api-docs.deepseek.com/api/list-models/)、[工具往返](https://api-docs.deepseek.com/zh-cn/guides/tool_calls/) 和 [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) 确认 `deepseek-flash`、非思考模式、函数声明和按 `tool_call_id` 配对的结果消息。
- **账户实测：** `scripts/probe_deepseek.py --fill-model` 鉴权读取 `/models`，发现 `deepseek-flash`；随后模型在 `auto` 模式下选择 `lookup_receipt`，传入预期票号。后端在收到调用后才生成 64 位随机回执，按原调用 ID 发回，第二次模型回复包含该回执。三项均通过后只补填本地 `LLM_MODEL`。此探针工具不暴露在应用的工具列表里。
- **能证明的范围：** 当时该账户可调用这个 API 模型名并完成一次完整工具往返；没有读取账户余额或锁定供应商内部权重版本。报告不保存鉴权头、密钥或原始 HTTP 转储。

## 真实应用：经 Vite 代理的四轮对话

最终版本执行 `.venv/bin/python scripts/smoke.py --live`，然后独立读取本机 SQLite 核对工具记录。测试输入是 [1UBQ 链 A 的 76 aa 泛素](https://www.rcsb.org/fasta/entry/1UBQ/display)。下表时间为 **2026-11-19 UTC**，取自该次成功会话，不是模拟时间。

| 时间 | 用户输入 | 后端实测结果 |
| --- | --- | --- |
| 03:00:47 | 中文请求 + 76 aa，无模型 | `ask_model`；保存待选序列。本次第一轮没有工具调用或任务 |
| 03:00:49 | `ESMFold2` | 真实 `predict_structure`；序列核对为 76 aa，模型 `esmfold2`；返回 `prediction_unavailable` |
| 03:00:52 | `Use the same sequence with Protenix.` | 真实 `predict_structure`；同一序列、模型 `protenix`，仍未创建任务 |
| 03:00:56 | 中文查询一个新生成且不存在的任务 UUID | 真实 `get_job_status`；`job_not_found`；未生成假状态或结果链接 |

四轮完成后，后端直连恢复出 8 条消息且顺序一致，数据库该会话任务数为 0。当前 `predict_structure` 的合法输入只走到 JobService 的“执行器尚未接入”回执，两次模型选择都**没有**调用对应的结构模型。

**浏览器实测：** 在本机聊天页选择泛素样例并发送，观察到等待提示、发送按钮禁用；收到 76 aa 的选模追问后刷新，已完成的消息仍存在。随后输入 `ESMFold2` 并按 Enter，页面显示正确长度、模型和“没有创建任务或生成结构”。「新对话」能打开独立空白界面。见[实测截图](../examples/screenshots/round-2-chat.jpg)。第一轮的断连/超时截图只说明历史版本，本轮没有在浏览器里重新等满 70 秒。

## 离线测试与构建

- `bash scripts/check.sh`：**68 passed**；`tsc --noEmit && vite build` 成功。pytest 使用临时 SQLite 和 HTTPX 上游替身，不读取真实账户来运行测试。
- 覆盖单条 raw/FASTA、大小写与空白、1/500/501 aa、非法字符与 Unicode、多条记录、拒绝改写/截断、未知模型/工具、会话隔离和重启恢复。也覆盖重试去重、冲突调用 ID、工具循环上限、模型错误声称成功、鉴权/额度/限流/异常响应及拒绝重定向。
- 真实本机 HTTP：`8000` 直连和 `5173` 代理均通过健康检查、422 非法 POST、404 未知会话；健康检查不请求模型。
- `.venv/bin/python -m pip check`：依赖一致。确认 `backend/.env` 被 Git 忽略，权限为 `600`；只在内存中比对，没有在 Git 候选文件、前端构建产物或本机 SQLite 文件中匹配到密钥内容。

## 尚未验证

MiMo 未实际调用，本项目只接入 DeepSeek。ESMFold2 的 Biohub 账户权限、额度、推理和结构导出未实测；Protenix 的 CLI、可用 GPU、权重/CCD 加载及 Mini 推理未实测。第一轮的官方链接 HEAD 200 不等于模型能运行。未安装大型权重、创建预测任务或演示三维结果。后续先做两条明确标注的 Mock 工作流，再逐个验证真实适配器。
