# 第六轮验收 · 真实聊天触发 Protenix Mini

2026-11-20（Asia/Shanghai）。**第六轮 Colab 实测通过，回传 ZIP 已在 Mac 上通过只读校验。** 会话 `3de221aa-1c0a-4d45-a411-698de8d81434`，任务 `94e78e41-5605-4be1-ae66-8b3f795d818a`。[原始结果包](../examples/outputs/round6-protenix-94e78e41-5605-4be1-ae66-8b3f795d818a.zip) · [第六轮笔记本](../colab/protenix_chat_round6.ipynb)

## 四项实测状态

| 环节 | 结果 | 已核对的证据 |
| --- | --- | --- |
| 真实聊天与工具往返 | 通过 | DeepSeek 工具往返、聊天回执和任务记录对应同一 UUID |
| 官方 GPU 推理 | 通过 | Protenix Mini 生成一条 76 aa 泛素链，mmCIF 与 PDB 均有 602 个原子 |
| Mol* 展示 | 通过 | Colab 浏览器对原任务进行了结构展示和交互检查 |
| 浏览器下载 | 通过 | 原任务预览和附件接口均通过，Colab 浏览器实际下载并通过刷新检查 |

原始 mmCIF 的 SHA-256 为 `bf53eabe23228d2ce7ac11c653186dc9b79d79347fd1851d45988357dc6cedda`，导出 PDB 为 `d879db64ec1b39b93b55ffbb5919f4681ac5a3eb2266baf414865825c9220dd1`。

第五轮的独立推理编号为 `3c130b48-360c-43c0-8e67-2d78e0a90f3a`，免费 T4 已生成含 602 个原子的单链泛素。第六轮校验器会拒绝该归档和运行编号。第三轮已实测真实 DeepSeek 和两条 Mock 路线。第四轮的 ESMFold2 Real 聊天任务收到 Biohub HTTP 451。本轮没有向 Biohub 发请求。[第五轮原始归档与校验](verification-round-5.md) · [第三轮](verification-round-3.md) · [第四轮](verification-round-4.md)

## 执行位置与复现条件

| 位置 | 执行内容 |
| --- | --- |
| Colab 内核 | 前三单元复用第五轮原有代码。GPU 环境和已校验权重放在 `/content/protenix-round5`。第六轮后端环境、独立数据库和归档放在 `/content/protenix-round6` |
| Colab 的一个 FastAPI 进程 | 在随机的 `127.0.0.1` 端口同时提供原应用的 API 和构建好的前端。通过真实 HTTP 提交聊天；DeepSeek 工具结果与任务在同一个 SQLite 事务提交后唤醒单并发 worker。该 worker 通过同机子进程调用官方 CLI。验收完成即关闭进程 |
| Colab 的浏览器 | Headless Chromium 在同一运行时访问上述回环端口，打开已有会话，读原数据库、原任务目录。正常路径上，从聊天到下载使用同一个后端进程。旋转、缩放、下载和刷新期间检查聊天请求数为零 |
| Mac | 本轮已实际运行离线 Chrome 验收。取回真实 ZIP 后可复核结构、日志和摘要。如 Colab 的浏览器不可用，Mac 可用原会话和任务的已保存回复及坐标完成只读网页演示。该路径会将浏览器证据另存并标记为 `mac_archive` |

第六轮仅向 DeepSeek 官方 HTTPS 接口发送正常聊天所需的内容。Colab Secrets 的 `DEEPSEEK_API_KEY` 经匿名管道进入后端内存。归档使用文件白名单，包含脱敏请求回执，不包含认证头、环境文件、数据库转储或模型权重。私有回环端口无需隧道。预测完全使用免费 GPU，DeepSeek 占用用户已有的对话额度。[DeepSeek 工具调用](https://api-docs.deepseek.com/guides/tool_calls) · [Colab Secrets](https://github.com/googlecolab/colabtools/blob/main/google/colab/userdata.py)

模型为官方 `protenix==2.0.0` 的 `protenix_mini_default_v0.5.0`。固定种子 101、4 个循环、5 个扩散步、1 个样本、FP32、Torch 内核和 LayerNorm，关闭 MSA、模板、fusion、TF32。CLI 超时 1800 秒。检查 T4 计算能力 7.5、Python 3.11.13、PyTorch 2.7.1 / CUDA 12.6、116 个推理依赖，以及 Mini 权重和四个缓存文件的来源、大小、CRC64 和 SHA-256。后端使用独立环境。[官方包](https://pypi.org/project/protenix/2.0.0/) · [资源核对](resource-check.md)

## 离线实测

- `bash scripts/check.sh` 通过 130 项 pytest、TypeScript 类型检查和 Vite 生产构建。本机后端 `pip check` 通过。保留既有单并发、超时、CLI 失败、错序列、错任务、缺失或损坏的结构及 Real 失败处理测试。Vite 对既有的 Mol* 按需加载块给出体积提示。
- 第六轮专门模拟了**推理成功后结构 HTTP 检查中断**。先取出已写好的 mmCIF、PDB 和 CLI 日志，再恢复同一任务。请求计数为一次聊天 POST、两次替身 LLM 往返、一次 CLI 预测。替换工具结果的任务 ID、mmCIF 标识、PDB 或下载字节，复核均拒绝。另用临时凭证执行了笔记本原单元，验证只通过标准输入交付，已提交时跳过 Secrets。模拟上游 401 时保留脱敏诊断，任务数为零。并发启动第二个验收进程会被文件锁阻止。[回归测试](../backend/tests/test_round6.py)
- `.venv/bin/python scripts/check_protenix_browser.py --round6` 在 Mac 用临时 SQLite、脚本化 DeepSeek 和 CLI 替身，从正常回环 HTTP 发出一次聊天。真实 Chrome 在原后端及只读归档服务分别打开同一任务，均观察到旋转、缩放、成功下载和刷新。一次实测中，两次画布的有色像素均从 246 变为 267、365。测试坐标来自 1UBQ，临时归档随测试清理。[浏览器脚本](../frontend/tests/browser-check.mjs)
- 七个代码单元通过 Python 编译和 Jupyter `nbformat.validate`。内嵌 ZIP 的文件清单和源码已逐项比对。生成器可重建同一份笔记本。第五轮原笔记本 SHA-256 仍为 `54bb02384ef17c5aabc3c840e7c9a127e8cb27b8fdfd4091870d2e5c1bc13ccd`。如更新源码或前端，先构建前端，再用 `.venv/bin/python scripts/build_round6_colab.py` 重建。[生成器](../scripts/build_round6_colab.py)
- 用 uv 为 Linux x86_64 / Python 3.11.13 从官方 PyPI 解析后端锁文件，19 个版本均匹配。浏览器使用 Node 24.22.3 和项目锁定的 Playwright 1.62.1，安装器验证两份发行包的摘要。Linux 安装计划选择 Chromium Headless Shell 151.0.7922.34，本机请求官方 Linux 下载地址返回 HTTP 200。该次离线检查只核对了安装计划。后续 Colab 运行的浏览器证据见上表。[Node 发布摘要](https://nodejs.org/dist/v24.22.3/SHASUMS256.txt) · [Playwright 浏览器安装](https://playwright.dev/docs/browsers)

## 结果留存与失败恢复

首次提交前将 `request_id` 落盘。重跑单元时，若 SQLite 已提交该请求，笔记本使用只读路径，继续读取原会话和任务。终态失败也会保留原错误。聊天提交之前的鉴权错误可在同一会话修正 Secrets 后重试。运行时被回收后，以已经下载的 ZIP 接续复核。

推理一旦完成，先写一份可下载的 ZIP，再查结构预览和下载接口、操作浏览器。画布通过时即写截图和浏览器记录；下载通过时再登记落盘文件。第 7 单元可随时下载当时已经取得的证据。若聊天尚未产生任务，诊断 ZIP 使用请求 UUID 命名。

| ZIP 内的文件 | 记录的事实 |
| --- | --- |
| `request.json`、`provider.jsonl`、`reply.json`、`turn.json`、`conversation.json` | 用户原文、请求 UUID、DeepSeek 请求及返回的模型标识、工具调用和回传、已提交会话与任务 |
| `job.json`、`input.json`、`events.jsonl`、`protenix-input.json`、`cli-events.jsonl` | 正常 API 任务状态、UTC 时间、worker 输入、官方 CLI 输入、参数、诊断和退出状态 |
| `hardware.json`、`versions.json`、`backend-versions.json`、`resources.json` | T4、CUDA、实际安装的两个环境和五份资源的校验记录 |
| `prediction.cif`、`structure.pdb`、`manifest.json` | 官方原始样本、应用导出结构和逐文件 SHA-256。逐个核对链、残基、原子标识及坐标，允许 PDB 精度引起的 0.001 Å 差异 |
| `structure-http.json`、`browser.json`、`chat.png`、`molstar.png`、`protenix-real-<任务UUID>.pdb` | 分别记录结构 API 预览/附件回复、真正的浏览器画布及下载。未到达的环节保留待验状态，程序执行错误可见于 `issue.json` |

## 在 Mac 复核原任务

把 ZIP 放进 `examples/outputs/`。以下命令在项目根目录执行，通配符适用于只有一份第六轮回包的情况。已有多份时用本次的确切文件名。网页复核需要前端生产构建和本机 Chrome。

~~~bash
.venv/bin/python colab/round6.py verify examples/outputs/round6-protenix-*.zip
.venv/bin/python colab/round6.py mac-view examples/outputs/round6-protenix-*.zip
~~~

第一条验证归档摘要、调用与结构的对应关系，并分别报告已有的 GPU、画布和下载证据。第二条在 Mac 打开浏览器操作原会话，把新的截图、浏览器记录和下载放入 ZIP 同级的 `…-mac/`。如需答辩时亲手旋转，运行下面的命令并打开打印的本机地址。按 Ctrl+C 结束。该进程只提供原任务的三个 GET 资源。[只读查看与校验实现](../colab/round6.py)

~~~bash
.venv/bin/python colab/round6.py serve examples/outputs/round6-protenix-*.zip
~~~

**答辩演示。** 第六轮可用归档演示真实聊天触发官方推理的同一任务，并在 Mac 复核该任务的结构。第四轮 ESMFold2 Real 保留当时的 451 失败记录。
