# 外部资源核对

## 第六轮 · 2026-11-20

第六轮笔记本沿用第五轮免费 T4 的模型、推理依赖和五个资源文件。已核对 Linux x86_64 / Python 3.11.13 的后端 19 项锁定依赖，以及 Node 24.22.3 Linux 发行摘要和 Playwright 1.62.1 的浏览器安装计划。第六轮回传归档已通过校验：Colab 上的真实聊天、官方推理、Mol* 展示、同任务下载及刷新均通过。已有 DeepSeek 对话额度和免费 T4 分别承担聊天和预测。[第六轮验收及运行位置](verification-round-6.md)

## 第五轮 · 2026-11-20

**免费 Colab T4 已完成一次独立泛素推理。** 本机核对了 PyPI 官方 `protenix==2.0.0` wheel 及 SHA-256 `be4584dda688e0518ce12909d8d51d0a0868e7daa2bbb95cbac17440c0ac309f`，检查了 CLI 注册、15 个调用选项、模型选择、输出命名、CUDA 7.x 分支和失败处理。选定权重为 **`protenix_mini_default_v0.5.0`**。本机没有执行官方模型前向计算。 [PyPI 发行包](https://pypi.org/project/protenix/2.0.0/#files) · [模型表](https://github.com/bytedance/Protenix/blob/v2.0.0/docs/supported_models.md) · [推理入口](https://github.com/bytedance/Protenix/blob/v2.0.0/runner/inference.py)

锁定的目标为 Linux x86_64、CPython 3.11.13、PyTorch 2.7.1 和 CUDA 12.6。用 uv 0.9.18 根据 PyPI 元数据解析了 Linux 环境的 116 项版本，锁内的 cuEquivariance 系列统一为 0.8.0。T4 的计算能力为 7.5。官方 7.x 分支使用 `fp32` 和两个 `torch` 三角运算，本项目还显式设置 `LAYERNORM_TYPE=torch`、关闭 fusion 与 TF32。笔记本用一次实际 CUDA 张量运算及 `protenix pred -h` 检查新环境。本次回包记录了 Tesla T4、匹配的 116 项安装版本和 1.71 秒模型前向耗时。显存记录为启动时快照，峰值未测。 [依赖清单](../colab/requirements-linux-py311.lock) · [官方依赖](https://github.com/bytedance/Protenix/blob/v2.0.0/requirements.txt) · [内核说明](https://github.com/bytedance/Protenix/blob/v2.0.0/docs/kernels.md) · [NVIDIA 计算能力](https://developer.nvidia.com/cuda/gpus) · [Colab 资源限制](https://research.google.com/colaboratory/faq.html)

下列五个官方对象本轮 HEAD 均返回 HTTP 200。大小和 CRC64 来自对象存储的响应头，合计 **1,192,159,061 字节**。笔记本在临时磁盘逐字节计算校验值，仅在比对成功后将下载文件纳入缓存，并另存 SHA-256。 [官方 URL 映射](https://github.com/bytedance/Protenix/blob/v2.0.0/protenix/web_service/dependency_url.py) · [下载和校验实现](../colab/resources.py)

| 官方资源相对路径 | 字节数 | TOS CRC64 |
| --- | ---: | ---: |
| `checkpoint/protenix_mini_default_v0.5.0.pt` | 537049294 | 10972385948284009591 |
| `common/components.cif` | 490777362 | 15584011929812638962 |
| `common/components.cif.rdkit_mol.pkl` | 142498117 | 8545945069051395908 |
| `common/clusters-by-entity-40.txt` | 21699572 | 12223273734315499485 |
| `common/obsolete_release_date.csv` | 134716 | 14600707826131585206 |

已在本机用相同下载器实际取回最后一项，CRC64 相符，SHA-256 为 `a4f3f63ac5d7eebd78b07995cc669b9eccd6f5d8813c9492c9df02868893cf33`。前四项在本机只取响应头。Colab 回包记录了全部五项资源的大小、CRC64 与 SHA-256。用户确认此次使用免费 Colab 配额。 [单文件笔记本](../colab/protenix_mini_ubiquitin.ipynb) · [第五轮分项验收](verification-round-5.md)

## 历史记录

**第四轮 · 2026-11-20**。Biohub key 已由本机后端读取，免费额度由用户确认。从聊天提交了单个 ESMFold2 Real 泛素任务，官方折叠请求收到 HTTP 451，未取得结构。Protenix 仍缺已落实的免费 GPU 环境、官方 CLI、Mini 权重及公共缓存。账户、资源和新旧证据的核对结果见[第四轮记录](verification-round-4.md)。

第三轮：已从 RCSB 获取 1UBQ 实验坐标并固定校验值，安装并验证 Mol* 5.13.1 和 Gemmi 0.7.5。真实 DeepSeek 工具调用能分别创建 ESMFold2 Mock 和 Protenix Mock 任务；没有运行任一真实预测模型。[第三轮实测](verification-round-3.md)

**2026-11-19 更新：** 已选定一家运行时 LLM：DeepSeek。账户鉴权的 `/models` 列出 `deepseek-flash`；已完成真实工具往返和应用内联调，见[第二轮实测证据](verification-round-2.md)。MiMo 未调用；ESMFold2 / Protenix 的推理权限和执行结果没有变化。以下保留第一轮当时的核对记录。

## 第一轮：基础通信前的资源状态

核对日期：**2026-11-17（Asia/Shanghai）**。文档可阅读、链接可访问、账户有权限和模型实际成功运行是四种不同证据。

## 当前环境与实际证据

| 项目 | 实际检查结果 | 限制 |
| --- | --- | --- |
| 项目起点 | 仅 `AGENTS.md`、`PRD.md`、`ARCHITECTURE.md`，无应用代码或项目 `.env` | 原设计文档保留 |
| 系统 | macOS 26.4 / Darwin arm64；系统 Python 3.9.6 | 默认 PATH 无 Node/npm/uv；未取得内存容量，不能据此估算推理能力 |
| 可用开发运行时 | Codex bundled Node 24.22.3、pnpm 11.25.0、Python 3.12.14 | 脚本兼容正常安装；便携运行时路径不写死进业务代码 |
| LLM 配置 | 检查项目配置文件与常见 LLM/DeepSeek/MiMo/OpenAI 环境变量，仅输出是否存在；均未发现可用配置 | **未发起鉴权请求或真实 LLM 工具调用**；用户计划之后购买 |
| ESMFold2 配置 | 未发现 ESMFold2/Biohub/Forge 密钥配置 | 无账户权限/额度证据；未请求预测 |
| Protenix 本机 | 系统 Python 未安装 `protenix`；未找到 `nvidia-smi`/`nvcc`，未配置 Protenix 路径 | Apple Silicon 不提供 NVIDIA CUDA；未检查到任何已分配的远程 GPU，不推断远端必然不可用 |
| Protenix Mini 权重链接 | 对官方 `protenix_mini_default_v0.5.0.pt` 发出 HEAD：HTTP 200，Content-Length 537,049,294 bytes | **只读取响应头**，没有下载、校验或加载权重 |
| CCD 链接 | `components.cif` HEAD 200（490,777,362 bytes）；`components.cif.rdkit_mol.pkl` HEAD 200（142,498,117 bytes） | 只证明入口可达；没有下载、解析或证明完整依赖可用 |

没有扫描个人密码库、其他项目的私有配置或导出环境变量值；没有安装大型预测软件/权重。HEAD 文件地址来自 [Protenix 官方下载映射](https://github.com/bytedance/Protenix/blob/main/protenix/web_service/dependency_url.py)。

## 候选 LLM：文档确认，均未实际调用

**DeepSeek**：官方当前模型表列出 `deepseek-flash`（文档映射 DeepSeek-V4.1-Flash-1017）和 `deepseek-v4-pro`。OpenAI 兼容 Chat Completions 入口为 `POST https://api.deepseek.com/chat/completions`，Bearer API key 鉴权。候选先用 `deepseek-flash`；它是可变供应商别名，不能声称锁定了远端权重。[模型表](https://api-docs.deepseek.com/quick_start/pricing/) · [接口](https://api-docs.deepseek.com/api/create-chat-completion/)

提交 JSON Schema `tools`，读取 `assistant.tool_calls` 中的名称、JSON 参数和调用 ID，后端校验后执行，再将原助手消息和带对应 `tool_call_id` 的 `role: tool` 消息回传。官方工具示例显式设置 `thinking: {type: "disabled"}`，适合最小探针；如启用 thinking，需要遵守 `reasoning_content` 回传规则。`strict` 是 beta 能力，不作为 MVP 前置条件。[工具调用指南](https://api-docs.deepseek.com/guides/tool_calls/) · [thinking 约束](https://api-docs.deepseek.com/guides/thinking_mode/)

**Xiaomi MiMo**：官方工具往返示例使用 OpenAI 兼容接口，Base URL 为 `https://api.xiaomimimo.com/v1`，请求 `tools` 并以 `tool_call_id` 关联工具结果；thinking 下的工具历史需要保留 `reasoning_content`。该指南部分例子仍写旧版本模型，不能照抄旧模型 ID。[工具历史说明](https://platform.xiaomimimo.com/docs/en-US/usage-guide/passing-back-reasoning_content)

当前官方首页列出 `mimo-v2.6-flash` / `mimo-v2.6-pro`，并公告 V2.5 系列于 2026-10-21 停用。候选为 `mimo-v2.6-flash`；购买时再次核实账户可访问模型和用于自建应用的 API 额度，不能把编码工具订阅当成已验证的通用 API 权限。[当前官方模型与停用公告](https://mimo.mi.com/docs/en-US)

**待用户准备**：一家供应商的服务端 API key、官方 Base URL、准确模型名，以及可用的赠送/付费额度。按 README 写入本地 `backend/.env`，只告知已配置。没有这些条件，本轮不发送空密钥探针，不把固定回复写成 LLM 验证成功。

**下一次探针判定**：实际发送带一个无副作用测试函数的请求；确认模型返回合法工具调用；本地校验参数并执行；按调用 ID 回传工具结果；确认第二次响应。记录供应商、请求/返回模型标识、UTC 时间和脱敏结果。单纯聊天返回 200、手写工具 JSON 或 Codex 写出代码均不足以通过。

## ESMFold2：官方访问方式

官方 Biohub 文档提供 `esm` SDK，客户端为 `esm.sdk.forge.SequenceStructureForgeInferenceClient`，URL 为 `https://biohub.ai`，需要 Biohub 账户 API token。文档的快速单序列变体为 **`esmfold2-fast-2026-05`**；另有 `esmfold2-2026-05`。这不是旧 ESMFold；后续不得使用旧 `esmfold_v1` 或旧折叠接口替代。[官方快速开始与模型表](https://docs.biohub.ai/models/esmfold2)

本轮只确认官方入口与模型名称，没有安装 SDK。账户注册、token、免费/实验室 credits、速率限制、输入长度限制、返回对象与结构导出、实际超时行为均未以本账户验证。官网能浏览不代表 API 免费可用；本项目 500 aa 是应用限制，不能写成供应商官方限制。

接入前还须在官方 API reference/对应 SDK 版本中核实完整输入输出协议，再用短单链请求保存实际结构文件并验证坐标。尚未固定“已验证可用”的 SDK 版本、请求参数或种子支持。

## Protenix：官方运行路径

官方提供 PyPI `protenix` 包和 CLI `protenix pred`（`predict` 的别名）；当前仓库 `main` 的包版本文件为 `2.0.0`，它不是本项目已安装/已锁定的版本。安装时应在独立环境锁定实际验证过的包版本/提交，并先检查该安装的 `protenix pred -h`。[安装与 CLI 文档](https://github.com/bytedance/Protenix/blob/main/docs/training_inference_instructions.md) · [版本源码](https://github.com/bytedance/Protenix/blob/main/protenix/version.py)

当前官方源码要求 Python >=3.11，依赖包括 torch 2.7.1、CUDA 12 专用 cuEquivariance、Triton 和 DeepSpeed。优先计划实验室/免费 Linux NVIDIA GPU 环境。源码存在 CPU 分支，不能据此声称 macOS/MPS 已支持或在本机可以合理完成推理；本轮没有安装或测速。[包元数据](https://github.com/bytedance/Protenix/blob/main/setup.py) · [依赖](https://github.com/bytedance/Protenix/blob/main/requirements.txt) · [内核说明](https://github.com/bytedance/Protenix/blob/main/docs/kernels.md) · [CPU/CUDA 分支](https://github.com/bytedance/Protenix/blob/main/runner/inference.py)

选 **`protenix_mini_default_v0.5.0`** 作为首次候选，避免 `mini_esm` 带来的额外 ESM2-3B 资源；实际尚未运行任何变体。官方 CLI 文档给出的参数包括 `--input`、`-o`、`--model_name`、`--seeds`、`--use_msa false`、`--use_template false`。输入为一个顶层列表项、一个 `proteinChain`、`count: 1`。Mini 模型自身支持 MSA，但 CLI 可关闭；这不代表有 MSA 与无 MSA 的精度相同。[模型变体](https://github.com/bytedance/Protenix/blob/main/docs/supported_models.md) · [输入格式](https://github.com/bytedance/Protenix/blob/main/docs/infer_json_format.md)

关闭 MSA/模板不等于无需权重和 CCD；须分别准备并验证。官方推理资源表的 500 tokens / 6.1 GB 是特定基准，不是 Mini 的最低显存承诺，不能当作本项目设备保证。训练文档的 TB 级数据要求也不是本轮单链无 MSA 推理的必需下载。

## 设计约束与缺口

- 未发现本轮基础通信与原设计冲突；保持一个后端进程、React/TypeScript/Vite、FastAPI/Pydantic、仅本地启动。
- 原设计的“真实 LLM”和“双模型真实运行”仍受资源制约，**没有被固定回复替代**。预测按零新增费用规划；本轮未购买、未创建服务账户、未安装权重。
- 同会话记忆、序列校验、异步任务、每模型 Real/Mock、持久化及结构输出均是后续必做项，本轮不宣称完成。
- 第三方文档支持更多残基、复合物或配体，并不放宽本项目单链、20 标准氨基酸、500 aa 等约束。
