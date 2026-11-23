[简体中文](./README.md) | **English**
# Protein Chat

A conversational web application for running protein structure prediction workflows. Protein Chat accepts a single amino acid sequence through a chat interface, routes the request to ESMFold2 or Protenix, tracks the prediction job, and displays the resulting structure in an interactive 3D viewer.

The application is built with **React**, **FastAPI**, and **DeepSeek tool calling**. Prediction jobs are validated and recorded by the backend, processed by a single worker, and displayed with **Mol\***. It supports both remote inference and a local-to-Google-Colab workflow for users without a dedicated GPU.

> **Model results are explicitly labeled.** Mock Mode uses an existing experimental structure for workflow testing; it does not perform protein structure prediction. See [Inference status](#inference-status) for what has been tested with real models.

## Features

- **Conversational requests:** submit a sequence in English or Chinese, select a model, and use follow-up instructions such as "Use Protenix for the same sequence."
- **Tool-based routing:** the LLM extracts the requested model and sequence; FastAPI validates the input before calling the appropriate prediction adapter.
- **Tracked jobs:** queued, running, completed, and failed states; persistent conversation and job records in SQLite; automatic status updates in the browser.
- **Structure inspection:** validated PDB outputs, interactive Mol* visualization, and downloads associated with each job.
- **Multiple execution paths:** ESMFold2 via Biohub or OpenProtein, Protenix Mini via a configured CLI or Google Colab, and a clearly identified Mock Mode.
- **Reproducible testing:** offline tests, browser checks, and archived evidence of a real Protenix inference run.

## Architecture

```text
Browser (React + Mol*)
    |
    v
FastAPI  --  DeepSeek (intent, parameters, tool calls)
    |
    +-- input validation / conversation context
    +-- SQLite (conversations, jobs, execution records)
    +-- single background worker
             |
             +-- ESMFold2 adapter --> Biohub / OpenProtein API
             +-- Protenix adapter --> local CLI / Google Colab
             +-- Mock adapter     --> reference PDB structure
             |
             v
       structure validation (Gemmi)
             |
             v
       job-specific PDB --> Mol* viewer / download
```

The language model handles conversation and tool selection; it does **not** generate protein coordinates. A prediction is marked complete only after the backend receives and validates its output. Job records include the input sequence, model and mode, timestamps, execution status, and relevant result or error information.

## Inference status

The following describes the project's **verified state in November 2026**, not a guarantee of availability for every account or region.

| Backend | Implementation and verification |
| --- | --- |
| **Protenix Mini (real)** | A real single-chain prediction of 76-residue ubiquitin was completed on a Google Colab T4 GPU. The resulting mmCIF/PDB files contained 602 atoms. The chat-to-tool-to-Protenix-to-structure-viewer workflow was also verified in Colab. See [verification record](docs/verification-round-6.md). |
| **ESMFold2 via Biohub** | The remote adapter submitted a real request for `esmfold2-fast-2026-05`, but the API returned **HTTP 451 (region restricted)** on 2026-11-20. No predicted coordinates were obtained from that request. See [failure record](docs/verification-round-4.md). |
| **ESMFold2 via OpenProtein** | The API integration was implemented and checked against the documented protocol. Authenticated end-to-end inference has **not yet been verified**; an unauthenticated model query returned HTTP 403. |
| **Mock Mode (both models)** | The chat, job, visualization, and download workflow was tested with the experimental ubiquitin structure [PDB 1UBQ](https://www.rcsb.org/structure/1UBQ). These outputs are labeled `mock` and must not be interpreted as model predictions. |

Real Protenix inference requires access to a compatible CUDA GPU, either through a local/remote installation or a Google Colab runtime. The web app itself runs locally without a GPU.

## Quick start

### Requirements

- Python **3.12** recommended (Python 3.11 or newer)
- Node.js **24** and pnpm **11.25.0**
- A WebGL-capable browser (tested with Google Chrome)
- A DeepSeek API key for live conversational requests

The development setup has been tested on macOS / Apple Silicon. Initial dependency installation requires access to PyPI and npm.

### 1. Install dependencies

From the repository root:

```bash
bash scripts/setup.sh
```

### 2. Configure the backend

```bash
cp -n backend/.env.example backend/.env
chmod 600 backend/.env
```

Edit `backend/.env` to add your own `LLM_API_KEY`. For a first run, use the two mock backends:

```dotenv
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash
LLM_API_KEY=YOUR_DEEPSEEK_API_KEY
ESMFOLD2_MODE=mock
PROTENIX_MODE=mock
```

The supplied `backend/.env.example` is the reference for supported settings. Check that the configured LLM model is available to your account. Never commit `backend/.env` or API credentials.

### 3. Start the application

In **terminal 1**, run:

```bash
ESMFOLD2_MODE=mock PROTENIX_MODE=mock bash scripts/dev-backend.sh
```

In **terminal 2**, run:

```bash
bash scripts/dev-frontend.sh
```

Open **http://127.0.0.1:5173/**. The FastAPI documentation is available at **http://127.0.0.1:8000/docs**, and the health endpoint at **http://127.0.0.1:5173/api/health**.

The health endpoint reports local configuration and selected modes; a successful health check does not establish that an external model API is reachable. Stop either service with `Ctrl+C` in its terminal.

### 4. Try a conversation

Use the built-in ubiquitin example, or paste this 76-residue sequence:

```text
MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG
```

Start a new conversation and send the sequence without a model name. The agent should ask which model to use. Reply `ESMFold2`, then follow up with `Use Protenix for the same sequence.` The two mock jobs should appear separately, with progress indicators and view/download actions when complete.

You can also try `Predict ABCZ123 using ESMFold2.` to check invalid-sequence handling. Refreshing the page should restore the current conversation and its job cards.

**In Mock Mode, both model choices display reference coordinates from PDB 1UBQ.** The job metadata and downloaded filenames identify them as simulated outputs.

## Running real predictions

### Protenix Mini with Google Colab

There is a handoff workflow for machines without a CUDA GPU:

1. Stop the existing backend if it is running, then launch `bash scripts/dev-backend.sh --colab`. Start the frontend normally with `bash scripts/dev-frontend.sh`.
2. Submit a **Protenix** request from the chat page. Download the job-specific notebook from the resulting task card.
3. Upload the notebook to [Google Colab](https://colab.research.google.com/), select an available **T4 GPU** runtime, and execute its four cells. Colab performs the prediction; no local GPU or notebook API key is required for this handoff.
4. Download the generated `protenix-result-<job-id>.json`, then upload it to the same task card in Protein Chat. The backend checks that the returned structure belongs to the original job before enabling 3D viewing and PDB download.

Keep the local backend running during the handoff; the result must be returned within one hour. Free Colab GPU availability is not guaranteed. This workflow works through file exchange and does not require exposing the local server to the internet.

Two standalone notebooks are also included:

- [`colab/protenix_mini_ubiquitin.ipynb`](colab/protenix_mini_ubiquitin.ipynb): run and verify a real ubiquitin prediction with the official Protenix Mini CLI.
- [`colab/protenix_chat_round6.ipynb`](colab/protenix_chat_round6.ipynb): reproduce the verified chat-to-prediction-to-viewer workflow on a Colab T4. This notebook requires a DeepSeek key stored in **Colab Secrets** as `DEEPSEEK_API_KEY`.

For a CUDA host with Protenix installed, the backend can invoke the CLI directly:

```bash
PROTENIX_MODE=real \
  PROTENIX_EXECUTABLE="/absolute/path/to/venv/bin/protenix" \
  PROTENIX_ROOT_DIR="/absolute/path/to/model-cache" \
  JOB_TIMEOUT_SECONDS=1800 \
  bash scripts/dev-backend.sh
```

See the [Protenix verification notes](docs/verification-round-5.md) and [end-to-end run](docs/verification-round-6.md) for prerequisites and expected outputs.

### ESMFold2 via OpenProtein or Biohub

ESMFold2 uses hosted inference rather than local GPU execution in this project. The integration supports two providers, but **a successful real ESMFold2 prediction has not been demonstrated in the recorded tests**.

**OpenProtein:** Add `OPENPROTEIN_USERNAME` and `OPENPROTEIN_PASSWORD` to your local `backend/.env`, then check account/model access:

```bash
.venv/bin/python scripts/probe_openprotein.py
ESMFOLD2_PROVIDER=openprotein ESMFOLD2_MODE=real \
  JOB_TIMEOUT_SECONDS=900 bash scripts/dev-backend.sh
```

**Biohub:** Add `ESMFOLD2_API_KEY` to `backend/.env` and configure the documented Biohub endpoint/model. Run the backend with `ESMFOLD2_MODE=real` and an appropriate timeout. The recorded attempt encountered HTTP 451; access depends on the provider's regional restrictions, permissions, and available quota.

Provider documentation: [OpenProtein ESMFold2](https://docs.openprotein.ai/python-api/structure-prediction/Using_ESMFold2.html) · [Biohub ESMFold2](https://docs.biohub.ai/models/esmfold2). Do not submit repeated real requests while diagnosing a failed or timed-out job, since they may consume external compute credits.

## Tests and verification

Run the main offline checks from the repository root:

```bash
bash scripts/check.sh
```

This includes backend tests, TypeScript checks, and a Vite production build. Additional checks are available:

| Command | Purpose |
| --- | --- |
| `.venv/bin/python scripts/smoke.py` | Verify health and basic HTTP error handling after the services start. |
| `.venv/bin/python scripts/check_protenix_browser.py` | Exercise a browser-based chat, structure viewer, download, and refresh using controlled test dependencies. Requires Chrome and a built frontend. |
| `.venv/bin/python scripts/smoke.py --live` | Run a short live DeepSeek conversation with mock predictions. **Consumes LLM API credits.** |
| `bash scripts/demo-failures.sh` | Start an isolated failure-demo backend on port 8001; see the [verification guide](docs/verification-final.md) for the corresponding frontend and browser checks. |

If you have a saved end-to-end Protenix result archive under `examples/outputs/`, you can verify it and view the recorded structure locally without rerunning the GPU prediction:

```bash
.venv/bin/python colab/round6.py verify examples/outputs/round6-protenix-*.zip
.venv/bin/python colab/round6.py serve examples/outputs/round6-protenix-*.zip
```

Open the local address printed by the `serve` command. These commands **replay an archived result**; they do not start new inference. If the archive is not present, generate and download one using the Colab notebook described above.

## Data, API, and scope

The app accepts **one protein chain** as a raw sequence or single-entry FASTA input. It supports the 20 standard amino acids and sequences of **1-500 residues**. Invalid input is rejected rather than silently altered.

| Endpoint | Use |
| --- | --- |
| `POST /api/chat` | Send a message, invoke the runtime agent, and create a prediction job when appropriate. |
| `GET /api/conversations/{id}` | Retrieve a conversation and its associated jobs. |
| `GET /api/jobs/{id}` | Read the status, metadata, and errors for a job. |
| `GET /api/jobs/{id}/structure` | Retrieve or download the validated structure for a completed job. |

SQLite stores conversation history and job metadata in `data/app.sqlite3`. Job-specific input, event records, and structure files are stored under `data/jobs/`. Gemmi checks structure content before results are made available. Incomplete jobs are not automatically resumed after a backend restart.

**This is a local, single-user research prototype, not a public web service.** It has no user authentication, uses a single worker, and is intended to run on loopback addresses only. Do not expose it directly to the public internet. The current scope excludes protein complexes, ligands, MSA/template workflows, and training or fine-tuning prediction models.

## Project files and further documentation

| Path | Contents |
| --- | --- |
| `frontend/` | React interface and Mol* integration. |
| `backend/` | FastAPI service, agent, adapters, persistence, and job execution. |
| `scripts/` | Setup, startup, diagnostics, and tests. |
| `colab/` | Protenix inference notebooks and archive verification utilities. |
| `examples/` | Reference structures, fixtures, and optional saved result packages. |
| `docs/` | Architecture and verification details, execution records, and development notes. |

- [Overall verification and reproduction notes](docs/verification-final.md)
- [Real Protenix end-to-end run](docs/verification-round-6.md)
- [ESMFold2 Biohub failure record](docs/verification-round-4.md)
- [Reference-structure provenance](examples/fixtures/README.md)
- [External resource and access notes](docs/resource-check.md)

Protein Chat uses the [Protenix](https://github.com/bytedance/Protenix) and [ESMFold2](https://github.com/Biohub/esm) model ecosystems, [Mol*](https://molstar.org/) for structure visualization, and [RCSB PDB 1UBQ](https://www.rcsb.org/structure/1UBQ) for mock-mode reference coordinates. Their respective terms and licenses apply.
