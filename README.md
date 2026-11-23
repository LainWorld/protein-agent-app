# Protein Chat · 对话式蛋白质结构工作台

用中文或英文提交单条蛋白质序列。真实 DeepSeek 负责追问和调用工具；FastAPI 核验原文后把任务写入 SQLite，单个后台 worker 按顺序执行。任务卡会自动刷新，完成后可用 Mol* 旋转/缩放并下载该任务的 PDB 文件。

## 老师复现演示，从这里开始

演示顺序为「本机新会话 → 两个 Mock 任务 → 第六轮真实结构回放」。任务书的 76 aa 泛素可直接由聊天页填入。新会话使用真实 DeepSeek；双 Mock 不占用预测算力。第六轮真实结构可以完全离线复核。

1. **环境和安装。** 在解压后的项目根目录打开终端。准备 Python 3.12、Node 24、pnpm 11.25.0 和支持 WebGL 的浏览器，本机以 Chrome 验收。首次安装需要联网。运行下面两行。检查会生成只读归档页面所需的前端构建。
   ```bash
   bash scripts/setup.sh
   bash scripts/check.sh
   ```
2. **配置聊天。** 首次运行用 `cp -n backend/.env.example backend/.env` 建立服务端配置，执行 `chmod 600 backend/.env`，用编辑器填入自己的 `LLM_API_KEY`。模板默认使用 `deepseek-flash`。已有配置可继续使用。若只查看历史真实结果，可直接到第 5 步，无需 key。
3. **启动。** 在两个以项目根目录为工作目录的终端分别执行下面两条命令。若端口上已有本项目服务，先确认其模式；需要切换时在原服务终端用 Ctrl+C 正常结束，再按这里启动。临时模式只对这次后端进程生效。
   ```bash
   ESMFOLD2_MODE=mock PROTENIX_MODE=mock bash scripts/dev-backend.sh
   bash scripts/dev-frontend.sh
   ```
   打开[健康页](http://127.0.0.1:5173/api/health)，确认 `llm_configured` 为 true 且两个 `prediction_modes` 都为 `mock`。健康页仅检查本机配置，第一轮聊天才能确认供应商可达。
4. **新跑聊天。** 在[工作台](http://127.0.0.1:5173/)点「新对话」→「泛素 · 先发序列」→「发送消息」。看到选模追问再回 `ESMFold2`，接着回 `Use the same sequence with Protenix.`。记录第二个编号，用「请查询本会话任务 完整编号 的状态」追问。依次在两张完成卡上打开三维结构，拖动、缩放、下载，核对文件名中的模型、`mock` 和编号。刷新确认任务恢复。最后发送 `请用 ESMFold2 预测这条序列：ABCZ123`，应收到非法字符提示，仍只有两张任务卡。
5. **查看已保存的真实推理。** 在第三个终端运行下面两行，打开第二行打印的**完整本机地址**。页面可旋转、缩放、下载原任务的 Real PDB。推理由第六轮在免费 T4 上完成，本步骤只读取归档，演示结束按 Ctrl+C。
   ```bash
   .venv/bin/python colab/round6.py verify examples/outputs/round6-protenix-*.zip
   .venv/bin/python colab/round6.py serve examples/outputs/round6-protenix-*.zip
   ```

[逐项验收与证据](docs/verification-final.md) · [Kimi 提示词与 8 分钟讲稿](docs/defense-kimi.md) · [现场操作卡](docs/defense-guide.md) · [一页开发总结（PDF）](docs/development-summary.pdf)。下文保留各轮的资源条件与复现方法。导师允许 ESMFold2 先用 Mock，第四轮的 451 失败截图可在新电脑直接查看；历史本机会话链接需要当时的数据库。

**第六轮已在免费 Colab T4 完成端到端验收。** 真实 DeepSeek 调用工具创建任务，官方 Protenix Mini 生成单链 76 aa 泛素（602 个原子）。同一任务通过 Colab 浏览器的 Mol* 展示、下载与刷新检查。[分项验收与结果包](docs/verification-round-6.md) · [复现笔记本](colab/protenix_chat_round6.ipynb)

**第五轮已接入 Protenix Real。** 免费 Colab T4 已生成项目的 76 aa 泛素结构，本机已逐一核对 mmCIF 和 PDB 中的 602 个原子。笔记本内置序列和运行文件，上传清单只有一个 `.ipynb`。聊天调用同机 CLI 的路线已通过离线浏览器验收，官方模型的聊天端到端实测见第六轮。[Colab 笔记本](colab/protenix_mini_ubiquitin.ipynb) · [第五轮验收](docs/verification-round-5.md)

**2026-11-20 的第四轮实测**从聊天提交了 76 aa 泛素。ESMFold2 Real 任务向 Biohub 请求 `esmfold2-fast-2026-05`。平台返回 **HTTP 451（地区访问受限）**，任务失败，未取得预测坐标。启动本机服务后可直接打开这次会话，查看失败原因。 [本轮会话](http://127.0.0.1:5173/?conversation=34a160b3-d570-4ee9-8771-6e0d3015e4c2) · [验收记录与截图](docs/verification-round-4.md)

第三轮已用真实 DeepSeek 和浏览器走完 ESMFold2 Mock 和 Protenix Mock 两条路线。两者展示和下载相同的泛素实验坐标，每个任务的下载名含 `mock`。 [RCSB PDB 1UBQ](https://www.rcsb.org/structure/1UBQ)

## 第六轮 · 从聊天到 Protenix Real 和 Mol*

1. 用自己的 Google 账号打开 Colab，通过「文件 → 上传笔记本」选择 **`colab/protenix_chat_round6.ipynb`**。约 1.5 MB 的单个文件内置了序列、运行包和前端。选择「运行时 / Runtime → 更改运行时类型 → T4 GPU → 保存」。如果只有付费选项，停在这里等待免费配额。[打开 Colab](https://colab.research.google.com/) · [第六轮文件](colab/protenix_chat_round6.ipynb) · [免费资源说明](https://research.google.com/colaboratory/faq.html)
2. 左栏点钥匙图标 **Secrets → Add new secret**。名称填 **`DEEPSEEK_API_KEY`**，值填已有的 DeepSeek API key，开启该行的 **Notebook access**。预测使用免费 GPU，真实聊天使用已有的 DeepSeek 对话额度。`backend/.env` 留在 Mac。[Colab Secrets 读取接口](https://github.com/googlecolab/colabtools/blob/main/google/colab/userdata.py)
3. 依次运行代码单元 **1 → 7**。第 1–3 单元应显示 `GPU OK`、`CLI OK`、`ASSETS OK · 5/5`。第 4–5 单元应显示 `BACKEND READY`、`BROWSER READY`。第 6 单元打印会话和任务 UUID，完整通过时显示 **`CHAT + GPU OK`**、**`STRUCTURE HTTP OK`**、**`MOLSTAR + DOWNLOAD OK`**。第 7 单元会下载并复核 **`round6-protenix-<任务UUID>.zip`**。把它原样放进 **`examples/outputs/`**。[证据目录](examples/outputs/)
4. 出现 `BROWSER PARTIAL` 仍可完成聊天和 GPU 推理。推理已经成功时，先运行第 7 单元下载已保存的结果。需要重试浏览器时，在**同一会话**重跑第 5–7 单元，已提交的聊天会进入只读路径。运行时已回收时，用下载的 ZIP 在 Mac 接着验收。反馈单元号、最后一条脱敏错误和已有任务 UUID 即可；遇到显存不足再附剩余 MiB。[同一任务的恢复及 Mac 查看](docs/verification-round-6.md#在-mac-复核原任务)

## 第五轮 · 在免费 Colab 上独立运行一次 Protenix Mini

1. 本人登录 Google 测试账号，打开 Colab，选「文件 → 上传笔记本」（欢迎窗口也有「上传」）。选择项目文件 **`colab/protenix_mini_ubiquitin.ipynb`**。序列、依赖清单和校验代码均已内置。`backend/.env` 留在本机。[打开 Google Colab](https://colab.research.google.com/) · [笔记本文件](colab/protenix_mini_ubiquitin.ipynb)
2. 在「代码执行程序 / Runtime → 更改运行时类型 / Change runtime type」中选择 **T4 GPU** 并保存。使用免费配额。若没有免费 GPU 或页面要求购买会员、计算单元，请停在这里，等免费配额恢复。[Colab 免费资源说明](https://research.google.com/colaboratory/faq.html)
3. 依次点第 **1 → 5** 个代码单元左侧的运行按钮。等当前单元显示下表中的标志再继续。

| 单元 | 做什么 | 成功输出 |
| --- | --- | --- |
| 1 | 检查 GPU、计算能力、显存、磁盘、驱动支持的 CUDA 和本机工具链 | `GPU OK`，设备为 T4，计算能力 7.5 |
| 2 | 安装独立 Python 3.11.13 和锁定依赖，实际执行 CUDA 张量运算，检查官方 CLI 版本和帮助 | `CLI OK`，Protenix 2.0.0、torch 2.7.1、CUDA 12.6 |
| 3 | 从官方地址下载 Mini 权重和四份缓存，逐文件核对字节数、CRC64 并计算 SHA-256 | `ASSETS OK · 5/5` |
| 4 | 对完整单链泛素启动一次官方 CLI 推理 | `PREDICTION OK` 和本次运行 UUID |
| 5 | 解析原始 mmCIF，逐原子比对导出的 PDB，校验结果包并下载 | `VERIFIED · 1 chain · 76 aa`、原子数和 ZIP 文件名 |

将 **`protenix-mini-ubiquitin-<运行UUID>.zip`** 原样放回项目的 **`examples/outputs/`**。若浏览器拦住下载，只需重跑第 5 单元，或从 Colab 左侧文件栏的 `/content/protenix-round5/` 下载同名 ZIP。包内有官方输入、原始 mmCIF、PDB、运行参数与 UTC 时间、实际软件和 GPU 版本、权重与缓存摘要、脱敏的 CLI 事件和文件清单。回包可在项目根目录独立复核，命令中的文件名换成实际下载名。

```bash
.venv/bin/python colab/ubiquitin.py verify "examples/outputs/protenix-mini-ubiquitin-实际运行UUID.zip"
```

若失败，只需反馈**单元号、GPU 名称和最后一条具体错误**。无 GPU 时提供配额提示即可。安装失败时提供包名和首条安装错误，下载失败时提供文件名和 HTTP 状态或 CRC 提示，内存不足时附剩余显存 MiB。第 3 单元支持断点续传。成功后的第 5 单元可单独重跑。

## 应用如何调用 Protenix Real

聊天任务的 worker 在后端所在主机启动官方 CLI。第五轮独立笔记本直接运行同一适配器，ZIP 的来源记录为 `standalone_colab`。第六轮从回环地址提交聊天，由提交后的 worker 启动 CLI，归档来源为 `round6_colab_chat_api`。

若后端所在主机已具备获准使用的免费 CUDA 环境、同一份隔离 CLI 及已验证缓存，可用以下一次性环境参数启动。将两个路径替换为该主机的实际路径。现有 `backend/.env` 可继续供本机后端使用。

```bash
PROTENIX_MODE=real PROTENIX_EXECUTABLE="/绝对路径/venv/bin/protenix" \
  PROTENIX_ROOT_DIR="/含有checkpoint和common的缓存目录" JOB_TIMEOUT_SECONDS=1800 \
  bash scripts/dev-backend.sh
```

CLI 也可由服务端 PATH 找到。模式与 ESMFold2 独立，支持的 `PROTENIX_MODEL` 为 `protenix_mini_default_v0.5.0`。健康接口中的 `prediction_configured.protenix` 只表示 CLI 路径和配置可用。每次任务先校验 CLI 版本，再使用种子 101、4 cycles、5 diffusion steps、1 sample，关闭 MSA 和模板。工作目录保留 `protenix-input.json`、`cli-events.jsonl`、官方 `output/<UUID>/seed_101/predictions/<UUID>_sample_0.cif` 和校验后供查看、下载的 `structure.pdb`。进程超时会终止整组子进程。 [官方模型表](https://github.com/bytedance/Protenix/blob/v2.0.0/docs/supported_models.md) · [官方 CLI](https://github.com/bytedance/Protenix/blob/v2.0.0/docs/training_inference_instructions.md)

同机资源就绪后，打开本机聊天页，点「English · Protenix」并发送。只创建一次新任务。等卡片完成，点「查看三维结构」和「下载 Real PDB」。验收已有单任务会话可运行 `bash scripts/check-browser.sh --real-conversation 会话UUID`。如需由浏览器脚本从零提交，可选 `--submit-real-protenix`，它会实际创建新任务。两种方式均核对显示与下载字节、任务 UUID 和摘要。

## 本机启动

在项目根目录运行。已验证 macOS arm64、Python 3.12.14、Node 24.22.3、pnpm 11.25.0。本机脚本能找到 Codex 自带运行时；其他电脑请安装 Python 3.11+（推荐 3.12）、Node 24 和 pnpm 11.25.0。无需 VS Code 插件。

```bash
# 在解压或检出的项目根目录运行
bash scripts/setup.sh
```

初次安装需要访问 PyPI 和 npm。Gemmi 0.7.5 解析结构，Mol* 5.13.1 在打开查看器时加载。ESMFold2 Real 复用已锁定的 HTTPX 0.28.1 请求 OpenProtein 或 Biohub 托管推理。已安装且锁文件没有更新时可跳过 setup。

本机已有 `backend/.env` 时直接使用，**不要覆盖**。新电脑从 `backend/.env.example` 复制，再用本地编辑器填 `LLM_API_KEY`，执行 `chmod 600 backend/.env`。下面是两条 Mock 演示使用的配置。第四轮的双模型设置见下节。

```dotenv
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash
ESMFOLD2_MODE=mock
PROTENIX_MODE=mock
MOCK_DELAY_SECONDS=3
JOB_TIMEOUT_SECONDS=30
```

后两项可省略。3 秒是为了观察轮询的模拟延迟。两种模式分别由服务端读取。未配置 DeepSeek 时健康接口和离线测试仍可用，正常聊天会报配置错误。

打开两个终端，均进入项目根目录，各自运行一个命令：

```bash
bash scripts/dev-backend.sh    # 终端一：127.0.0.1:8000，一个进程
bash scripts/dev-frontend.sh   # 终端二：127.0.0.1:5173
```

打开[本机聊天页](http://127.0.0.1:5173/)。关闭服务分别按 Ctrl+C。改后端配置后需重启；如果服务已在运行，无需再启动。FastAPI 的[接口说明](http://127.0.0.1:8000/docs)也只在本机可用。

## 通过 OpenProtein 运行 ESMFold2 Real

本项目可从聊天将一条序列交给 OpenProtein 的完整模型 `esmfold2`。2026-11-21 已按生产接口规范和官方客户端 `openprotein-python==0.17.0` 核对请求，匿名查询生产模型接口收到 HTTP 403。此轮接入尚待用有权限的账号完成首次真实预测。[官方模型说明](https://docs.openprotein.ai/python-api/structure-prediction/Using_ESMFold2.html) · [Fold REST 接口](https://docs.openprotein.ai/rest-api/fold.html) · [生产鉴权规范](https://api.openprotein.ai/openapi.json)

1. 登录 OpenProtein，确认账号有可用于本次 76 aa 泛素预测的免费额度或实验室已有权限。用本地编辑器在现有 `backend/.env` 填写 `OPENPROTEIN_USERNAME` 和 `OPENPROTEIN_PASSWORD`。保留原有 DeepSeek 设置。请仅在本机填写密码。[账号入口](https://app.openprotein.ai/) · [官方认证说明](https://docs.openprotein.ai/python-api/quickstart.html)
2. 在项目根目录执行 `.venv/bin/python scripts/probe_openprotein.py`。看到 `OPENPROTEIN MODEL OK` 表示账号登录成功且模型信息可读；实际推理权限及可用配额要看任务结果。
3. 如原后端正在运行，先在其终端 Ctrl+C。使用以下命令启动，另一个终端运行 `bash scripts/dev-frontend.sh`（已启动的前端可继续使用）。这次启动只切换 ESMFold2，沿用原有 Protenix 设置。
   ```bash
   ESMFOLD2_PROVIDER=openprotein ESMFOLD2_MODE=real JOB_TIMEOUT_SECONDS=900 bash scripts/dev-backend.sh
   ```
4. 在工作台点「新对话」→「泛素 · 先发序列」→「发送消息」，助手追问时回 `ESMFold2`。回执应显示 **OpenProtein** 和本地任务编号。服务端只提交一次，单链 A、无 MSA、1 个样本、3 次循环、50 步、种子 0，随后按远程任务编号轮询。也可用 `bash scripts/check-browser.sh --submit-real-esmfold2` 代替本步手动提交。[本机工作台](http://127.0.0.1:5173/)
5. 完成后用 `bash scripts/check-browser.sh --real-conversation 会话UUID` 复核已有会话的旋转、缩放、刷新和下载。会话 UUID 在页面地址栏，任务 UUID 在卡片上。原始 mmCIF、`openprotein-job.json`、输入和导出 PDB 在 `data/jobs/任务UUID/`，浏览器验收保存 PDB 和截图至 `examples/`。失败或超时先查任务卡；若已有远程编号，可用它在平台追踪原任务，避免重复提交。

## 通过 Biohub 运行 ESMFold2 Fast Real

1. 登录 Biohub 的 Developer Console，在 **API Keys** 创建 key，将完整值保存在现有 `backend/.env` 的 `ESMFOLD2_API_KEY`。在 **Credits** 核对可用赠送余额，在 **Rate Limits** 核对 Fast 模型权限。官方接受学术或非营利项目申请额外算力。公开资料未给出可据以保证每个账户能免费完成本次 76 aa 请求的统一额度。 [API Keys](https://biohub.ai/developer-console/api-keys) · [额外研究额度申请](https://info.biohub.org/biohub-additional-compute-credits)
2. 后端设置 `ESMFOLD2_MODE=real`、`PROTENIX_MODE=mock`。`ESMFOLD2_API_URL=https://biohub.ai` 和 `ESMFOLD2_MODEL=esmfold2-fast-2026-05` 是应用固定支持的地址和版本。重启后端使设置生效。本次以 `JOB_TIMEOUT_SECONDS=120 bash scripts/dev-backend.sh` 启动，进程参数只影响当次运行。
3. 打开本机聊天页，点「泛素 · 先发序列」，把开头改成「请用 ESMFold2 预测这条序列」，保留完整序列后发送一次。也可先发序列，等助手追问后再选 ESMFold2。新任务卡显示 **Real**、任务编号和请求的模型版本。仅在服务端收到了与本次请求匹配的有效坐标并校验 PDB 后，才会出现「查看三维结构」和「下载 Real PDB」。
4. 重查已有任务时直接打开会话链接。自动验收命令 `bash scripts/check-browser.sh --real-conversation 会话UUID` 只读取该单任务演示会话。仅在确认需要**新建**任务、官方访问正常且免费额度充足时才运行 `bash scripts/check-browser.sh --submit-real-esmfold2`。后者会从浏览器发送一条真实聊天消息；若已手动提交，请使用前者。成功时检查 Mol* 的旋转、缩放、下载与画布取得的字节，并在 `examples/` 保存证据。真实任务失败时记录原因、截取失败卡并返回退出码 2。

后端向官方 `POST /api/v1/fold` 发送已核对的序列和固定模型 ID，使用 Bearer 鉴权、JSON 响应、单序列无 MSA，并按官方客户端约定请求关闭缓存。同步 API 的上限是 768 tokens，本应用对标准单链输入采用 500 aa 上限。每个任务只发一次折叠请求。451 可由平台的地区限制引起，402 对应额度，429 对应限流；状态卡保留各自错误。超时后先核对该任务及平台记录，再决定是否新建。 [官方模型](https://docs.biohub.ai/models/esmfold2) · [fold 接口](https://docs.biohub.ai/api/protein/models/fold) · [输入上限](https://docs.biohub.ai/api/protein/models/overview)

## 用 76 aa 泛素走完两条 Mock 路线

1. 点「泛素 · 先发序列」，再点「发送消息」。首次应询问模型，不创建任务。真实聊天会向 DeepSeek 发送消息、序列和必要的会话上下文，使用对话 API 额度。
2. 回复 `ESMFold2`。下方出现带 UUID 的 Mock 任务卡；排队或运行中时仍可聊天。前端大约每两秒查一次任务，终态后停止；轮询、查看、下载、刷新均不调用 LLM。
3. 回复 `Use the same sequence with Protenix.`，应新增另一个任务编号。可问“这个任务完成了吗？”，或带任务 UUID 发问；回答来自同会话数据库记录。
4. 在两张已完成卡分别点「查看三维结构」，拖动旋转、滚轮缩放，可点「复位视角」。点「下载 Mock PDB」，核对文件名中的模型与 UUID 和当前卡一致；文件的 REMARK 也有相同编号、来源和 Mock 说明。
5. 刷新页面，会恢复当前会话与任务卡。新对话不继承旧序列和任务。若状态请求断开，卡片显示“状态待确认”，不因网络错误宣告任务失败或成功。

序列支持单条 raw 或单条 FASTA，只去空白、转大写、去 FASTA 标题，限 20 种标准氨基酸、1–500 aa。边界不清时独立粘贴序列或写在“序列：”之后。不得修复残基、截断用户输入或使用模型猜出的序列。

## 检查

| 命令（根目录） | 验证范围 | 费用 |
| --- | --- | --- |
| `bash scripts/check.sh` | pytest（临时 SQLite、可控上游）、TypeScript、Vite 生产构建 | 离线 |
| `.venv/bin/python scripts/check_protenix_browser.py` | 使用前一条命令的前端构建，临时后端、LLM 和 CLI 替身，从聊天操作 Mol*、下载并刷新。需本机 Chrome | 离线，不消耗 GPU 或对话额度 |
| `.venv/bin/python scripts/check_protenix_browser.py --round6` | 第六轮回环聊天、原任务画布与下载、同一归档在 Mac 只读复核。两次 Chrome 操作和一次测试聊天均使用临时目录 | 离线，无 GPU 或对话费用 |
| `.venv/bin/python scripts/smoke.py` | 服务启动后，直连与 Vite 代理的健康、422、404 | 无 LLM 请求 |
| `.venv/bin/python scripts/smoke.py --live` | 真实 DeepSeek 四轮：缺模型追问、ESMFold2 Mock、换 Protenix Mock、状态查询；还核对两个文件、校验和与会话恢复 | 使用少量对话额度，无预测费用 |
| `bash scripts/check-browser.sh --conversation 会话UUID` | 用上一步最后打印的会话 UUID，打开现有 Chrome 临时配置，读取两张已完成卡、操作真实画布、实际下载、刷新、保存截图 | 无 LLM 请求；仅用于上述两任务验收会话 |
| `.venv/bin/python scripts/probe_deepseek.py` | 独立探测账户模型清单与真实工具往返；`--fill-model` 只在探测成功后补填空模型字段 | 两次对话补全 |

`curl --fail http://127.0.0.1:5173/api/health` 可确认正在运行的配置。第四轮实测的 `prediction_modes` 为 `{"esmfold2":"real","protenix":"mock"}`。每条路线的 `prediction_configured` 和对话的 `llm_configured` 只检查本机配置；上游访问结果见实际任务。

**复现失败（无 API 费用）。** 运行 `bash scripts/check.sh` 即覆盖执行异常、超时、无文件、空/坏文件、只有水分子、跨任务文件、成功后被修改/删除、以及服务重启。若要亲眼看失败页面，可在三个终端分别运行：

```bash
bash scripts/demo-failures.sh           # 终端一：独立临时库、脚本化 LLM 替身，8001
bash scripts/demo-frontend.sh           # 终端二：带“隔离故障演示”标签，5174
bash scripts/check-browser.sh --faults  # 终端三：真实 Chrome，提交两个故障样例并保存截图
```

需要已安装的 Google Chrome，也可以设置 `CHROME_PATH` 指向现有兼容浏览器。Playwright Core 不会安装浏览器。手动检查时打开[故障演示页](http://127.0.0.1:5174/)，输入 `Use ESMFold2. Sequence: ` 或 `Use Protenix. Sequence: ` 后**紧接完整 76 aa 序列**（见[示例](examples/fixtures/README.md)）。这个临时上游只识别这两条测试消息，不是运行时 Agent；无任何故障注入 HTTP 入口。前者执行异常，后者返回无蛋白质坐标的文件；两张卡应只显示失败原因，不能查看/下载。

## 数据与接口

- `POST /api/chat`：传 `message`，可选 `conversation_id` 和稳定的 `request_id`。工具回执带任务 UUID；会话、工具记录和任务预留在同一事务提交，再唤醒 worker。上游失败不产生孤立任务；成功请求重试不重复入队。
- `GET /api/conversations/{id}`：返回本会话的消息和任务编号。浏览器可通过 `/?conversation=会话UUID` 打开指定会话，并在 localStorage 中记住当前会话。
- `GET /api/jobs/{id}?conversation_id=...`：状态、模式、版本、时间、错误、来源和结果可用性。`GET /api/jobs/{id}/structure?conversation_id=...` 返回该任务坐标；加 `&download=true` 下载同一字节。拒绝跨会话查询；失败/未完成返回 409。路径由服务端决定。
- `data/app.sqlite3` 记录参数、序列、UTC 时间、模式、状态、摘要和相对结果路径；`data/jobs/<UUID>/` 隔离保存输入快照、事件日志和 PDB。Mock 的版本为 `mock-1UBQ-v1`，不使用随机种子。获得输出后用 Gemmi 核实蛋白质坐标；读取时再验归属、摘要和可解析性。重启时遗留排队/运行任务标为失败，不自动重跑。会话无鉴权，只用于本机单用户；不要开放公网或启动多 worker。

[第五轮 Protenix 验收](docs/verification-round-5.md) · [第四轮 ESMFold2 验收](docs/verification-round-4.md) · [第三轮 Mock 验收](docs/verification-round-3.md) · [样例坐标出处](examples/fixtures/README.md) · [外部资源状态](docs/resource-check.md) · [开发总结](docs/development-summary.md) · [第二轮 LLM 验证](docs/verification-round-2.md) · [第一轮通信验证](docs/verification-round-1.md)。

## Mac 聊天页提交自己的序列，交互使用免费 Colab

如果已有后端，先在它的终端按 Ctrl+C。项目根目录运行 `bash scripts/dev-backend.sh --colab`；前端照常运行 `bash scripts/dev-frontend.sh`。在 http://127.0.0.1:5173/ 发送 Protenix 请求和完整单链序列。任务卡显示 Real、长度和编号。此启动模式只对 Protenix 启用交互式 Colab，普通启动方式仍使用原配置。

1. 从运行中的任务卡下载专属笔记本，在 Google Colab 的“文件 → 上传笔记本”打开。序列和任务编号已填入。选择免费 T4 并运行全部四个代码单元；使用者在 Colab 主动发起本次计算，无需在笔记本中配置密钥。
2. 最后一个单元下载 `protenix-result-任务编号.json`。回到原任务卡选择这个文件。后台核验记录、官方 mmCIF 中的任务标识、完整序列与坐标；通过后显示三维结构并开放 PDB 下载。若 CLI 失败，交回失败 JSON 可在卡中查看失败原因。
3. 从任务开始到交回结果最多一小时。请保持 Mac 后端运行。页面刷新可恢复任务；重启后端会结束未完成任务。卡片排队时，先完成前一张卡。浏览器拦截下载时可重复运行笔记本最后一个单元取回已写好的结果。

此方式仅在回环地址运行，无需公网隧道。每个使用者自行运行项目时使用自己的本地配置。Colab 单元中的序列和下载的结果均属于该次任务。
