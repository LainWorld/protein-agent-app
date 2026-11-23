# Development Guide

Build a small, reproducible conversational protein structure prediction app for the MRes assessment. Prioritize correctness and explainability. Use this summary for routine development; consult relevant sections of `PRD.md` or `ARCHITECTURE.md` only when details are needed.

## Constraints

- Use React + TypeScript + Vite, Python + FastAPI + Pydantic, and Mol*. Chat is the primary input; support Chinese and English requests for single-chain proteins.
- Use one backend process, SQLite for conversations/jobs, and local files for structures/logs. Keep adapters separate from the agent and job service. Avoid orchestration frameworks, distributed queues, authentication, public deployment, complexes, ligands, training, and MSA/template configuration UI.
- A real runtime LLM must perform tool/function calling. Codex-generated code or keyword routing does not satisfy this requirement. Integrate one provider through a thin client.
- External resources are initially unverified. Prefer free/laboratory resources; the user is willing to buy DeepSeek or Xiaomi MiMo API access if needed for the LLM. Prediction API/GPU resources remain under the zero-additional-cost plan. LLM access does not provide protein inference resources.
- Verify official APIs, model IDs, CLI flags, and access before implementation; pin working dependencies/configuration. Use official ESMFold2 access, never substitute older ESMFold. Use the official Protenix package/CLI in an isolated environment; try a Mini variant without MSA/templates first and record the actual variant.

## Required behavior

- Expose `predict_structure(sequence, model)` with model restricted to `esmfold2 | protenix`, and `get_job_status(job_id)`. Validate tool arguments server-side, return tool results to the LLM, bound the tool loop, and prevent duplicate execution of the same tool call.
- Ask for missing sequence/model; clarify ambiguous references. Reuse sequences and resolve job references within the same conversation only. Persist conversation context for refresh recovery.
- Accept one raw sequence or one FASTA record. Normalize only case, whitespace, and the FASTA header; never repair residues. Require the 20 standard amino acids, nonempty input, and an initial application limit of 500 aa plus backend-specific limits. Verify tool sequences match user input or confirmed history; reject multiple records and unsupported models.
- Return a job ID promptly; run predictions in the background with concurrency one and timeouts. Poll roughly every two seconds without calling the LLM. Use `queued → running → succeeded | failed`; interrupted queued jobs may also fail. After restart, mark unfinished jobs failed rather than silently resubmitting.
- Backend records determine status, result links, and mode. Mark success only after the correct job's output exists, is nonempty, parses, and contains protein coordinates. Show understandable failures for connection, execution, timeout, and invalid-output errors; never fabricate completion.
- Configure Real/Mock separately per model. Mock must identify its fixture source and visibly say it is an example structure, not a prediction for the submitted sequence; include `mock` in download names. Never silently fall back from Real to Mock. Implement real adapter paths even when resources prevent live verification, and document unverified parts.
- Save each job's sequence, model/version, mode, parameters, supported seed, status, UTC timestamps, output location, and errors in an isolated job directory/record. Keep secrets server-side and out of source/logs. Use argument lists for subprocesses and server-controlled download paths.

## Implementation order

1. Probe a real LLM tool call and check ESMFold2 access and Protenix compute/weights. Record resource gaps; continue independent work while access is pending.
2. Establish React/FastAPI communication, then integrate the LLM's extraction, clarification, and follow-up behavior.
3. Complete both Mock workflows: validation, persisted jobs, status polling, Mol* viewing, downloads, and error handling.
4. Connect real adapters one at a time, starting with available resources. Aim for one application-triggered real run per model; retain input/configuration/log/output evidence.
5. Validate and prepare submission. Work in small increments; report completed checks and remaining gaps. Keep setup commands in README and debugging history in the development summary, not this file.

## Acceptance and handoff

- Demonstrate both model routes, missing-model clarification followed by submission, same-sequence model switching, and truthful status queries using the assessment's 76 aa ubiquitin example.
- Reject empty/invalid sequences such as `ABCZ123`, multiple FASTA records, and unknown models without inference. Exercise execution failure and corrupt/missing output; show no fabricated result.
- Verify interactive rotation/zoom, downloads matching the displayed job, persistent Real/Mock labeling, and conversation recovery after refresh.
- Pass relevant pytest checks and frontend type/build checks. Use test doubles for routine tests; separately verify real LLM behavior and report which real prediction integrations were actually exercised.
- Deliver source, configuration templates, reproducible README, tests, example outputs/screenshots, an approximately one-page AI-assisted development summary with a genuine debugging case, and 6–8 slides for an approximately eight-minute presentation and live demo.
- Prediction Mock Mode is acceptable when resources are unavailable and real integration paths are documented. A missing real LLM leaves the runtime-agent requirement incomplete. Report each model's verification status honestly; saved results are not new inference.
