# Agent Workflows

> Status: **Stage 11 implemented** with the fake provider (one real planning request succeeded, 2026-10-24; other prompts and failure modes not exercised against the real API). Design: [ADR-0010](../decisions/ADR-0010-llm-gateway-and-agent-workflows.md). All five graphs, the gateway, redaction and evidence filtering are built; migration 0009 is written and tested on a disposable database only.

## Principle
Deterministic services first; a model only where interpretation adds value. Model output is data: it never overrides authorization, approval or sandbox policy, and it is always parsed into a closed schema and re-checked by deterministic code. Long-running execution stays in workers and the sandbox (Stages 7-9); graphs only read records and call the gateway.

## Components
```
api/agents.py (thin) -> services/agent_workflows.py (authorize, create agent_run, run graph, persist)
                          -> orchestration/graphs/* (LangGraph: nodes, conditional edges)
                               -> deterministic services (analyzer, check_catalog, policy, plans, findings...)
                               -> agents/* (prompt template + output schema + deterministic fallback)
                                    -> integrations/llm/gateway (the only model path)
                                         redact -> budget -> provider(timeout, retry) -> validate -> llm_usage
```

## Blueprint agents -> graphs (resolves Q20)
| Blueprint §7 | Handled by |
|---|---|
| 7.1 Project Analysis | Analysis graph |
| 7.2 Test Planning | Planning graph |
| 7.3 QA Execution Coordinator, 7.4 Security Testing Coordinator | Deterministic services (Stages 7-10); no agent |
| 7.5 AI/LLM Security | Planning (propose `llm_*` catalog checks) + Investigation (interpret output); scenario generation is Stage 13 |
| 7.6 Observability/Anomaly | Stage 12 (will reuse Investigation) |
| 7.7 Failure Investigation | Investigation graph |
| 7.8 Regression Test Proposal | Regression-proposal graph |
| 7.9 Verification | Verification graph |
| 7.10 Reporting, 7.11 Assistant | Stage 14 (reuse the gateway) |

## Common rules
- **State** is a typed dict (ids, hashes, validated intermediate data). It never holds a secret, an access decision, the text sent to a model or a command (the user's own request text is passed to nodes by the service, not stored in the trace). Every node loads records scoped by `project_id`.
- **Node kinds:** `deterministic`, `decision` (e.g. `should_call_llm`, with a recorded reason), `llm` (only via the gateway), `policy` (existing policy/catalog validation). Every node writes an `agent_steps` row (seq, node, kind, outcome, redacted detail, `llm_usage_id`).
- **Bounds:** graph recursion limit 12; no loops over model output; overall deadline 60 s; per call 30 s; 2 retries (timeout/429/5xx only, with backoff); invalid output gets **one** repair-free retry at most, then `degraded`.
- **Status of an `agent_run`:** `running` -> `succeeded` | `degraded` (deterministic result delivered, model part unavailable/blocked/invalid) | `failed` (no usable result, e.g. access lost or interrupted).
- **Degrade, don't fail:** model timeout, outage, budget block, schema failure or injection-looking output end `degraded` with a stable `degraded_reason` (`llm_timeout`, `llm_unavailable`, `budget_blocked`, `invalid_output`, `llm_disabled`, `deadline_exceeded`, `prompt_too_large`) and the deterministic result unchanged. If no `GEMINI_API_KEY`/model is configured, LLM steps are skipped (`llm_disabled`).
- **Cache:** key = hash(project, workflow, subject content hash, template version, model); hit = no call, step `cache_hit`, zero usage.
- **Authority:** nodes call existing services only. The graph package may not import `execution/`, `approvals` decision functions, `policy` writers or run creation (enforced by a test).

## Output schemas (all `extra=forbid`, bounded strings, enums)
- `PlanProposal`: up to 10 × `{check_id (must exist in catalog), params (validated by catalog), reason ≤ 300 chars}`. No risk, command, approval or target fields exist in the schema.
- `AnalysisInterpretation`: `summary`, `components[]`, `trust_boundaries[]`, `uncertainties[]`, each item with `basis` = ids of discovery facts it relies on (must exist) and `label` ∈ {`inference`, `hypothesis`}; never `fact`.
- `Investigation`: `classification` ∈ fixed failure classes, `causes[]` (≤ 5) each `{label ∈ likely|hypothesis, statement, evidence_ids ⊆ supplied ids, reproduction_steps[]}`; never `confirmed`.
- `RegressionDraft`: `title`, `rationale`, `target_path` (relative, no `..`, allowed extensions), `framework` ∈ supported, `code` ≤ 20 kB, `evidence_ids`, `expected_behavior`; stored only.
- `VerificationSummary`: `outcome_text`, `limitations[]` (≥ 1), `evidence_ids`; cannot carry a status.

## LLM gateway (implemented, Step 2)
`integrations/llm/`: `gateway.py` (`LLMGateway.call(ctx, request, deadline)`), `gemini.py` (only module importing the SDK; one attempt per call, SDK retries off, errors translated by status code without copying messages), `fake.py` (`FakeProvider`, `FakeClock` for tests), `budget.py`, `deadline.py`, `types.py`, `errors.py`; SQL in `repositories/llm_usage.py`. A graph node does: build a `GatewayRequest(purpose, template_version, system, prompt, output_schema)`, call the gateway with the workflow `Deadline`, and catch `LLMError`: its `.reason` becomes the `degraded_reason`, its `.usage_id` the step's `llm_usage_id`. The gateway returns only schema-validated output.
Per call: redact -> size check -> reserve budget (advisory lock; blocked calls are recorded and audited as `llm.budget_blocked`) -> attempts with `min(call timeout, time left)` and backoff, never past the deadline -> validate -> settle usage (tokens, estimated cost, latency, attempts, prompt hash; never prompt text).
Settings: `LLM_CALL_TIMEOUT_SECONDS` 30, `LLM_GRAPH_DEADLINE_SECONDS` 60, `LLM_MAX_RETRIES` 2, `LLM_INVALID_OUTPUT_RETRIES` 1, `LLM_RETRY_BACKOFF_BASE_SECONDS` 0.5, `LLM_MAX_PROMPT_CHARS` 60000, `LLM_MAX_OUTPUT_TOKENS` 2048, `LLM_PRICE_INPUT_PER_MTOK_USD` / `LLM_PRICE_OUTPUT_PER_MTOK_USD` (placeholders), `LLM_MAX_TOKENS_PER_RUN`, `LLM_MAX_COST_USD_PER_RUN`, `LLM_MAX_COST_USD_PER_DAY`, `GEMINI_API_KEY`, `GEMINI_MODEL`. With no key or model the gateway is disabled and workflows degrade with `llm_disabled`.

## Redaction and evidence filtering (implemented, Step 3)
`integrations/llm/redaction.py` (`PromptRedactor`, applied by the gateway to the system and user text of every call; counts returned as `result.redactions` / `error.redactions`, to be written into the trace step's detail) and `integrations/llm/evidence_filter.py` (`Excerpt`, `build_evidence_block`, `pick`, `with_data_rule`, `ALLOWED_KINDS`). A node builds its evidence like this: select records with `pick` (allow-listed fields only) -> make `Excerpt(id, kind, text, priority)` items with platform-generated ids -> `build_evidence_block(purpose, items, max_total_chars=...)` -> put `block.text` in the prompt and `with_data_rule(system)` in the system text -> after the call, reject any cited id not in `block.included_ids`. `block.summary()` (included / dropped by kind / dropped by budget / truncated / collapsed) goes into the step detail so a reviewer can see what the model was and was not shown. Evidence kinds per purpose: analysis (analysis_fact, manifest_fact, source_excerpt), planning (analysis_fact, catalog_check, user_request), investigation (log, test_case, finding, analysis_fact, source_excerpt), regression (investigation kinds + existing_test), verification (finding, scan_summary, test_case, log).

## Planning graph (implemented, Step 4)
Code: `agents/planning.py` (template `planning-v1`, `PlanProposal`, catalog and fact excerpts, cache key), `orchestration/planning_graph.py` (LangGraph `StateGraph`, recursion limit 12), `orchestration/trace.py`, `services/agent_workflows.py` (`run_planning`, `sweep_interrupted`), `repositories/agent_runs.py`, `api/agents.py`, `schemas/agents.py`. Nodes: `deterministic_select` (keywords; computes the cache key) -> `decide_llm` (disabled? cached?) -> `llm_propose` -> `validate_catalog` -> `store_draft_plan`. Trace outcomes seen in `agent_steps`: `matched`, `no_match`, `llm_disabled`, `cache_hit`, `call_model`, `ok` / a degraded reason, `nothing_fits`, `invalid_output`, `draft_created`, `no_proposals`. Result JSON on the run: `plan_id`, `check_ids`, `source` (`keywords` | `cache` | `model`), `reasons`, `rejected`, `message`.

## The five graphs (all implemented)
Every graph is a LangGraph `StateGraph` (recursion limit 12) whose nodes write `agent_steps`; each ends `succeeded`, `degraded` (deterministic part kept) or `failed`. Request: `POST /projects/{id}/agent-runs` with the fields below (a workflow accepts only its own).

| Graph | Request | Deterministic part (always) | Model part (only when it adds value) | Stored result |
|---|---|---|---|---|
| **Planning** `planning-v1` | `prompt`, optional `snapshot_id` | keyword selection of catalog checks; draft plan via `plans.store_plan` | only if no keyword matched; chooses catalog ids; cached per request+facts | `plan_id`, `check_ids`, `source`, `reasons`, `rejected` |
| **Analysis** `analysis-v1` | `snapshot_id` | loads the completed snapshot; counts of facts/inferences/gaps | interpretation (summary, components, trust boundaries, uncertainties), each claim labelled inference/hypothesis and citing evidence ids; uncited claims dropped; cached per snapshot hash | `deterministic` counts, `output`, `dropped` |
| **Investigation** `investigation-v1` | exactly one of `result_id` / `finding_id` | evidence (case messages, redacted log excerpts read through `runs.read_evidence`, finding fields), failure class (`assertion_failure`, `unclassified`, `scanner_finding`, `missing_dependency`, `syntax_error`, `timeout`, `infrastructure`, `not_executed`), standing limitation text | only for `assertion_failure` / `unclassified` / `scanner_finding`: up to 5 causes labelled likely/hypothesis (never confirmed), each citing shown evidence, with reproduction steps; cached per evidence hash | `classification`, `explanation`, `limitations`, `causes` |
| **Regression** `regression-v1` | exactly one of `result_id` / `finding_id` | eligibility (finding `verification_state` likely/confirmed, or a failed result with a failed case), evidence, framework hint, reuse of a live proposal for identical evidence | drafts one test file; code checks: path rules, size, parse-only syntax check (Python `ast`), risk flags (risky imports/calls), name overlap | a `regression_tests` row (`proposed`) and its id, `risk_flags`, `overlap` |
| **Verification** `verification-v1` | `finding_id`, `mode=prepare` or `mode=conclude` + `run_id` (+ `summarize`) | prepare: eligibility and a draft re-scan plan for the finding's own scanner and source; conclude: compares the run's result with the recorded `verification_attempts`, verdict `fixed_by_rescan` / `still_present` / `inconclusive` | conclude only, only if `summarize`: wording of the outcome with limitations | `plan_id` (prepare), or `verdict`, `reason`, `limitations`, `output` (conclude) |

Rules common to all: ids cited by a model must have been in the evidence it was shown; labels never include `fact`/`confirmed`; models cannot set a status, risk, approval or command (the schemas have no such field and `extra=forbid` makes one invalid); model prose is whitespace-normalised and length-capped; a model failure keeps the deterministic result; evidence reads are audited like downloads; access (`run` level) is checked at the route and again before any write.

Regression proposals are reviewed at `GET /projects/{id}/regression-proposals[/{pid}]` and `POST .../{pid}/decision` (`accepted` / `rejected` + note). A decision records who and when and writes an audit event; it does not write to the source, commit or run anything. A database trigger freezes the draft's content and allows only `proposed -> accepted | rejected` and `accepted -> verified`.

## Cost controls
Filter/dedupe before calls; cache by subject hash; focused excerpts with hard caps (default 12 kB prompt data, 1.5 k output tokens); bounded tokens/retries/time; per-run, per-project and per-day budgets from `llm_limits`; a blocked call is recorded (`blocked_by_budget`), audited, and degrades the run. Record model, tokens, latency, outcome, estimated cost, `prompt_hash` (not the prompt).

## Data (migration 0009 `0009_llm_gateway_agent_runs`: written and tested on a disposable DB, not applied to the real DB)
- `agent_runs`: project-scoped workflow record (workflow, subject, status, degraded reason, requester, input hash, template version, model, `used_llm`, `cache_hit`, result JSON, timestamps).
- `agent_steps`: append-only trace (run, seq, node, kind, outcome, detail JSON with counts and reason codes only, `llm_usage` id).
- `llm_usage` gains `outcome` (including `reserved`), `attempts`, `latency_ms`, `prompt_hash`, `template_version`, `agent_run_id`.
- `regression_tests` (existing) gains `project_id`, nullable `finding_id` and `result_id` (one of them required; deleting the result deletes its proposals), `agent_run_id`, the draft (`title`, `rationale`, `target_path`, `framework`, `code`, `expected_behavior`), `evidence_ids`, `risk_flags`, `overlap`, `decision_note`, size checks and the freeze trigger. Earlier rows (none were ever written by code) are kept with placeholder text; the downgrade deletes result-only proposals.

## API (all project-scoped; role capability plus project access; starting a run or deciding a proposal needs `run` access, so a read-only break-glass grant cannot start a model call)
`POST /projects/{id}/agent-runs` (10 per minute per user), `GET /projects/{id}/agent-runs[/{run_id}]` (read access; the detail includes the step trace), `GET /projects/{id}/regression-proposals[?status=]`, `GET .../regression-proposals/{pid}`, `POST .../regression-proposals/{pid}/decision`. Errors reuse the standard envelope; `budget_exceeded` surfaces as a degraded run (`budget_blocked`), not an HTTP error. `POST /findings/{id}/verify-fix` and `PATCH /findings/{id}` from Q77 were not needed: verification is a workflow, assignment stays unbuilt.

## Not in Stage 11
Real-time chat (14), report synthesis (14), anomaly/alert reasoning (12), LLM-security scenario generation (13), automatic code changes or commits, any model-initiated execution, a UI for agent runs (frontend track, Q116), asynchronous (worker) execution of graphs (Q101), and any real-Gemini verification (Q104).
