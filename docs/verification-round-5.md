# 第五轮验收 · Protenix Real

**2026-11-20（Asia/Shanghai）**。用户在免费 Colab T4 上完成一次官方 Protenix Mini 推理。本机复核了归档中的运行日志、输入和两份坐标文件，确认输出对应项目的完整 76 aa 泛素。 [本次结果 ZIP](../examples/outputs/protenix-mini-ubiquitin-3c130b48-360c-43c0-8e67-2d78e0a90f3a.zip) · [泛素笔记本](../colab/protenix_mini_ubiquitin.ipynb)

| 验收项 | 状态 | 已有证据和仍缺的证据 |
| --- | --- | --- |
| ① 免费 Colab 上的官方 Protenix Mini 生成可解析的 76 aa 泛素 | **实测通过** | CLI 选择 CUDA 并以 0 退出。mmCIF 与 PDB 均为一条 76 aa 的 A 链，602 个原子逐一匹配 |
| ② 从聊天创建 Protenix Real 任务，触发本次推理，并在 Mol* 查看和下载该任务结构 | **官方推理端到端未实测** | 离线已从聊天走到真实画布和浏览器下载，LLM 和模型 CLI 使用替身。真实验收还缺能在后端所在主机调用的官方 CUDA CLI、一次新聊天任务及其坐标和浏览器证据 |

本机为 macOS arm64，免费 T4 在 Colab 虚拟机内。应用用同机子进程执行 CLI，Colab 直接运行同一适配器处理内置泛素。两边各有自己的运行编号。回包校验只读取独立推理档案。项目继续使用一个本地后端，未设置隧道、远程服务或结果导入接口。

## 实现和运行证据

- 固定 PyPI **Protenix 2.0.0** 和权重 **`protenix_mini_default_v0.5.0`**。已实际下载并校验官方 wheel，在发行包内核对 `pred` 对应的 Click 命令和全部 15 个选项。T4 使用 FP32、Torch 三角注意力、Torch 三角乘法和原生 LayerNorm。关闭 fusion、TF32、蛋白 MSA、RNA MSA 和模板。显式设置 4 个循环、5 个扩散步、1 个样本和一个 CLI 支持的种子 101。 [官方发行包](https://pypi.org/project/protenix/2.0.0/) · [官方模型表](https://github.com/bytedance/Protenix/blob/v2.0.0/docs/supported_models.md) · [命令实现](https://github.com/bytedance/Protenix/blob/v2.0.0/runner/batch_inference.py)
- 输入为项目的 76 aa 泛素，纯大写序列的 SHA-256 为 `233b4b0b8c4616095bc3249f9375fc345d32af7deaef07117d0383c51d6f19aa`。官方 JSON 使用一个任务项、一个 `proteinChain`、`count=1`。样本名为服务端任务 UUID，独立笔记本也为新推理生成 UUID。 [项目序列](../examples/fixtures/README.md) · [官方输入格式](https://github.com/bytedance/Protenix/blob/v2.0.0/docs/infer_json_format.md)
- 聊天工具沿用 SQLite 单并发队列，数据库的 `seed` 列和任务的 `input.json` 均记录 101。worker 在新目录内执行版本检查和一次 `pred`，通过参数列表传入配置；环境只放行运行 CLI 所需的变量。日志记录 UTC、实际包版本、参数、退出码、分类错误和可识别的 CUDA/前向计算信息。 [适配器](../backend/app/adapters/protenix.py)
- 只读取该 UUID 和种子对应的 `*_sample_0.cif`。用 Gemmi 检查 CIF 数据块名、`_entry.id`、单链、完整序列、每个残基的 Cα 和可导出坐标。应用保存原始 mmCIF，并用附任务标记的 PDB 供同会话查看和下载。超时会终止 CLI 进程组，执行错误、错误目录、损坏或归属不符的结果均进入失败状态。 [官方输出目录和命名](https://github.com/bytedance/Protenix/blob/v2.0.0/runner/dumper.py) · [官方 CIF 写入器](https://github.com/bytedance/Protenix/blob/v2.0.0/protenix/data/utils.py)

## 本轮实际完成的检查

| 检查 | 结果 |
| --- | --- |
| 后端和前端 | `bash scripts/check.sh` 通过 125 项 pytest、TypeScript 类型检查及 Vite 生产构建。后端 `pip check` 通过。按需加载的 Mol* 块保留既有体积提示 |
| Protenix 任务与故障 | 16 项适配器专项用例通过。启动真实操作系统子进程作为 CLI 替身，测试正常输出、非零退出但遗留合法 CIF、退出零但写入 ERR、版本不符、OOM、超时和子进程终止、空/缺/坏文件、错误种子、序列、数据块或任务编号、Cα 缺失、NaN 和符号链接。失败项均检查 Real 标签、空结果和下载被拒绝 |
| 浏览器离线验收 | `.venv/bin/python scripts/check_protenix_browser.py` 通过。真实 Chrome 从聊天提交完整泛素，在临时后端的 Real 路线启动 CLI 替身。实际拖动和缩放后，画布检测到的结构像素由 242 变为 267、365。下载文件名、字节及 SHA-256 与显示任务匹配，刷新成功。输入坐标来自测试用的 1UBQ，测试库、截图和下载只保存在临时目录 |
| 笔记本与结果包 | Jupyter `nbformat.validate` 和五个代码单元的 Python 编译通过。重新构建得到相同笔记本。测试比对内置五个支持文件与仓库源码，断点续传及 CRC 失败路径通过。在临时目录运行独立推理控制、归档、回读和篡改测试。另用 Gemmi 0.6.7 导出替身样本，再用本机 0.7.5 重读同一个 ZIP，逐原子核对通过 |
| 资源访问 | 本机先核对官方 wheel 及五个资源的响应头，并下载校验了 CSV。Colab 回包中五份资源的来源、大小和 CRC64 与固定清单一致，实际安装的 116 个锁定包版本也全部匹配。 [资源大小和 CRC 清单](resource-check.md) |

一次离线排查发现，即使预测程序返回 0，也可能没有有效样本。官方 runner 会捕获单个样本的异常，写入 `ERR` 或在日志中报告失败。现在有专门用例让子进程正常退出并留下错误记录，另一个用例让同序列的 CIF 携带其他任务编号。两者都不会获得下载链接。 [官方异常处理](https://github.com/bytedance/Protenix/blob/v2.0.0/runner/inference.py)

修改适配器、校验代码或 Linux 锁文件后，在项目根目录运行 `.venv/bin/python scripts/build_protenix_colab.py` 可重新生成单文件交付物。`test_colab.py` 会比对发布的笔记本与当前源码。 [生成器](../scripts/build_protenix_colab.py) · [回归测试](../backend/tests/test_colab.py)

## Colab 真实运行的回包复核

| 项目 | 本次实测 |
| --- | --- |
| 运行归属 | 来源 `standalone_colab`。归档文件名、`run.json`、官方输入的样本名、mmCIF 的 `_entry.id` 和 PDB 的 `REMARK 950 JOB` 均指向 `3c130b48-360c-43c0-8e67-2d78e0a90f3a` |
| 环境与模型 | Tesla T4，计算能力 7.5，Python 3.11.13，PyTorch 2.7.1，PyTorch CUDA 12.6。Protenix CLI 2.0.0 实际调用 `protenix_mini_default_v0.5.0`，种子 101，FP32，4 个循环、5 个扩散步、1 个样本，关闭 MSA 与模板 |
| 时间与执行 | 2026-11-20 07:31:51.600–07:32:46.509 UTC，任务耗时 **54.91 秒**，其中日志报告模型前向 **1.71 秒**。一次 `pred` 调用，`cuda_selected=true`，退出码 0，终态 `succeeded` |
| 序列与结构 | 分别从 mmCIF 和 PDB 的坐标记录还原序列，与官方输入及项目泛素逐位一致。两份结构的 A 链均为残基 1–76，76 个残基都有 Cα。按链、残基编号与名称、原子名、替代构象和元素核对全部 602 个原子，最大坐标距离 **0.000825 Å**，在 PDB 导出容差 0.001 Å 内 |

ZIP 完整性检查及 `manifest.json` 内八个文件的 SHA-256 均通过。以下摘要可用于复核同一份归档及其中的两份坐标。

| 文件 | SHA-256 |
| --- | --- |
| 结果 ZIP | `e9b02ae9687a645327586868cc3c754eb59fa8037c478bc65b0f14bd80b4c801` |
| `prediction.cif` | `90151995b40e2ac5b1bcdbe33f7e2a00e3272f8b2a172b3a6b169df03620a614` |
| `structure.pdb` | `1a0d1fbbb9532ae8ad0a677cbf4185b8054b470628cf17e38d408633047950ff` |

在项目根目录可重现本次只读校验。

```bash
.venv/bin/python colab/ubiquitin.py verify examples/outputs/protenix-mini-ubiquitin-3c130b48-360c-43c0-8e67-2d78e0a90f3a.zip
```

**第二项仍待独立实测。** 验收需要真实聊天创建新任务，由该任务启动官方推理，再核对同一任务在 Mol* 显示和下载的结构。

## 历史结果

第三轮使用真实 DeepSeek 创建并展示了两条 Mock 任务。第四轮用真实聊天提交 ESMFold2 Real，Biohub 返回 HTTP 451，任务失败，未取得结构。本轮没有重交这些请求。 [第三轮记录](verification-round-3.md) · [第四轮记录](verification-round-4.md)
