# ADR-0011: Observability ingestion, deterministic alerts and the failure-to-test loop (Stage 12)

Status: **Accepted with amendments** (design written 2026-10-24; the owner then asked for Steps 2-8 to be built and Stage 12 completed, so the proposals below were implemented as written except where the amendments at the end say otherwise; ADR-0002 still needs its amendment for ingest keys, Q123). Owner decisions already taken (2026-10-24): (a) first-release ingestion is **authenticated, project-scoped HTTP push** of structured events plus Sentinel's own run/test/finding failures, with no agent on the target and no pulling from third-party systems; (b) alerts are **UI only** (no email or webhook); (c) event retention was asked and **not answered**, so the numbers below are a proposal (Q124). Opens Q123-Q132. Builds on ADR-0010 (gateway, redaction, investigation/regression graphs) and ADR-0002/0003 (identity, approvals). Blueprint sections 5.7, 5.8, 5.9, 7.6.

## Context
Stages 9-11 produce failures (test results, scanner findings) but nothing watches a running application, and a failure never feeds back into a proposed test unless a person opens the finding. The plan asks Stage 12 for ingestion paths, redaction, deterministic filtering/de-duplication/thresholds, correlation, UI alerts with acknowledgement, selective investigation and evidence-linked regression proposals. The schema has no table for any of it (DATABASE_SCHEMA "deferred"), `/alerts` is reserved but unspecified (API_DESIGN), and `PromptRedactor`, `agent_runs`, `regression_tests` drafts and the investigation/regression graphs already exist. OpenTelemetry, cost/latency anomalies and model-call telemetry are Stage 13 and are **not** designed here (SYSTEM_ARCHITECTURE listed OpenTelemetry under Stage 12; the plan and this ADR place it in Stage 13).

## Decisions

### 1. Sources (exactly two kinds)
| Source | What it is | Trust label shown to users |
|---|---|---|
| `external` | Structured events pushed by the project's own application or log shipper | "Reported by the application" (a claim, like a project's own JUnit report, Q67) |
| `internal` | Failures Sentinel itself recorded: `test_runs` ending `failed`/`timed_out`, `test_results` with status `failed`/`error`/`timed_out`, new or reopened `findings` | "Observed by Sentinel" (derived from existing rows by ids, never copied logs) |

Not supported in this stage (stated in the UI and API docs so absence is never read as health): pulling from Datadog/Sentry/Loki/CloudWatch or any third party, file tailing, syslog, OTLP/OpenTelemetry (Stage 13), trace storage, an agent or sidecar installed on the target, metrics scraping, and browsing/searching raw logs (Sentinel is not a log store; only de-duplicated groups and a few redacted samples are kept).

### 2. Ingestion endpoint and credential
`POST /ingest/v1/events` (outside `/projects/{id}`; the project comes from the credential). Request body: JSON, `{"events": [...]}`, at most 100 events and 256 KiB per request (checked on the stream before parsing; larger -> `413`). Response `202 {"accepted": n, "dropped": {"reason": count}}`; nothing else about the project is returned. Calls are idempotent per event only through the optional `event_id` (UUID, deduplicated for 24 h); retries without it may double count and the counts say so.

**Credential: project ingest keys** (Q123, needs the owner's confirmation because ADR-0002 said "no bearer tokens in the first release"; a push model with no browser session needs one machine credential, and this is the narrowest one):
- Format `sai_ing_<key_id>_<secret>`; the secret is 32 random bytes (urlsafe), shown **once** at creation; only a keyed hash (same pepper mechanism as session tokens) and the non-secret `key_id` are stored; compared in constant time.
- Scope: **one project, one capability** (write events). A key can read nothing, cannot reach any other endpoint, and is not a user: it has no role and every other route rejects it. Sessions/cookies are ignored on the ingestion route (so no CSRF surface), and the route rejects requests that carry a session cookie but no key.
- Lifecycle: created, listed (prefix, label, created by, last used, expiry) and revoked by project **managers** only (`POST/GET/DELETE /projects/{id}/ingest-keys`); default expiry 90 days, maximum 365; at most 5 active keys per project; revocation is immediate (checked on every request); create/revoke are audited (`ingest_key.create`, `ingest_key.revoke`). A key is never logged, never returned after creation, never placed in a URL or query string.
- Failures: unknown, expired or revoked key all return the same `401` body; failed attempts are throttled per source address; a disabled project policy returns `403 ingest_disabled` only to a valid key.
- Project opt-in: ingestion is **off by default** for each project (policy key `observability_ingest = {"enabled": false}`; a manager enables it). Reason: log data can carry personal and secret data, so collecting it is an explicit per-project choice (Q127). Production-labelled events are accepted only when this is enabled; ingesting data from production is observation, not testing, so it does not need the production-testing authorization, but redaction (3) and retention (9) apply in full.

### 3. Event schema v1 (strict; `extra=forbid`; every field bounded)
| Field | Rule |
|---|---|
| `event_id` | optional UUID |
| `timestamp` | optional RFC 3339; **advisory only**. The server's `received_at` is what every rule uses. A timestamp more than 24 h in the past or 5 min in the future is replaced by `received_at` and flagged `timestamp_untrusted` (Q131) |
| `level` | enum `warning`, `error`, `fatal`. `debug`/`info` are accepted but **dropped and counted** (`dropped.level_below_threshold`); lowering the floor is not offered in this stage |
| `service` | 1-64 chars, `[A-Za-z0-9._-]` |
| `environment` | enum `local`, `development`, `staging`, `production`, `unknown` |
| `message` | 1-2,048 chars |
| `error_type` | optional, 1-128 chars |
| `stack` | optional, at most 8 KiB and 60 frames, text |
| `attributes` | optional flat map, at most 20 keys, key `[a-z0-9_.-]{1,40}`, value string (<= 256) / number / bool; no nesting |
| `trace_id`, `span_id` | optional, W3C hex (32 / 16 lowercase hex); stored as **opaque references** for Stage 13, never resolved or fetched |
| `run_id`, `result_id`, `finding_id` | optional UUIDs; **claims**, verified server-side (7) |
| `release` | optional, <= 64 chars (deployment/version label) |

Invalid events are dropped individually with a reason count (`invalid_schema`, `too_large`, `quota`, `rate_limited`); one bad event never rejects the batch, and no event content is echoed in an error.

### 4. Redaction and storage hygiene (before anything is stored)
Every accepted event passes `sentinel_ai.core.event_redaction` before it touches the database, in this order: size/field allow-list (anything not in the schema is already refused) -> configured secret values by exact value -> credential shapes, URL credentials, private-key blocks, token formats, e-mail addresses, long high-entropy tokens (the **same pattern set as `PromptRedactor`**, factored into a shared module in Step 2 so the two cannot drift; behaviour of the gateway redactor must not change, covered by its existing tests) -> attribute **key** denylist (`password`, `passwd`, `secret`, `token`, `authorization`, `cookie`, `session`, `api_key`, `apikey`, `private_key`, `credential`, `ssn`, `card`; value replaced) -> control-sequence stripping. Replacement is `[REDACTED:<kind>]`; only per-kind counts are kept on the event. The raw payload is **never** persisted (not even on failure or in logs; request bodies are not logged). Remaining limits are those of Q113 and are repeated in the UI near samples ("redaction is pattern based; it can miss unknown secret shapes").

Stored text is data: always rendered as plain text, never as markup, never executed, never used as a path, query or template. Anything sent to a model passes the existing evidence filter and gateway redaction again (defence in depth) and keeps the "untrusted data" delimiters, so log lines cannot instruct the investigation graph.

### 5. Normalization, fingerprint, grouping (deterministic, versioned `fp-v1`)
`fingerprint = sha256(version, project_id, service, environment, level_class, error_type, normalized_message, top-3 normalized stack frames)`. Normalization replaces UUIDs, hex ids, numbers, quoted strings, IPs, e-mail remnants and absolute path prefixes with placeholders, and keeps only `file:function` of frames (no line numbers, so a deploy that shifts lines does not create a new group). Changing the rules means a new version string; groups never silently regroup (old groups keep their version). Quality of grouping is unmeasured (Q130).

Storage keeps **groups, hourly counts and a few samples**, not a raw stream:
- `event_groups`: one row per `(project, fingerprint)`: version, service, environment, level class, error_type, normalized message, first/last seen (`received_at`), total count, `has_stack`, sample cap counters.
- `event_buckets`: `(group, hour)` -> count (the basis of every rate rule; 30 days kept).
- `events`: at most **20 redacted samples per group** (the first 5 and the most recent 15; older ones are deleted by the writer), with correlation claims, the verification result of each claim, redaction counts and `timestamp_untrusted`.
- Caps that bound storage and cardinality attacks: **5,000 groups per project** (beyond that events land in one `overflow` group and `dropped.group_cap` is counted and alerted), **50,000 events/day/project** (`quota`), **600 events/min and 60 requests/min per key** (`rate_limited`, `429` + `Retry-After`).

### 6. Alerts: deterministic rules only; no model decides whether to alert
Rules are code with a version, each producing at most **one open alert per `(project, rule, subject key)`**; repeats update `last_seen`/`occurrences` instead of creating more. Threshold settings are the policy key `alert_thresholds` (organization defaults; a project manager may change values **within organization-set bounds** `alert_threshold_bounds`; invalid values are ignored in favour of defaults, as in `policy.py`).

| Rule | Fires when (defaults, all configurable) | Severity |
|---|---|---|
| `new_error_group` | a group of level `error`/`fatal` reaches 3 events in 15 min (1 for `fatal`) and was first seen inside that window | medium (`fatal`: high) |
| `error_rate_spike` | events of a group in the last hour >= 5 and >= 3x the median of its previous 24 hourly buckets (a group with fewer than 6 prior buckets is "no baseline" and uses the absolute threshold only, and says so) | medium |
| `recurrence` | a group whose alert was resolved receives events again | medium; the old alert is reopened (history kept) |
| `run_failed` (internal) | a run ends `failed`/`timed_out`, or a result is `failed`/`error`/`timed_out` (one alert per run, listing results) | by result severity mapping: failed = medium, timed_out/error = low |
| `finding_reopened` (internal) | an existing finding moves to `reopened` | the finding's own severity |
| `telemetry_gap` | ingestion was active (>= 1 accepted event in the previous 7 days) and none arrived for the silence threshold (default 6 h) | info |
| `ingest_dropping` | the project hit a quota, rate limit or group cap in the last hour | low |

Severity is a fixed table, not a model judgement. **Confidence** shown on an alert is one of `observed` (counts and times measured by Sentinel), never "probable cause". An alert states *what was measured*, *when*, *which component* (`service`/`environment` or run/test/finding), the *evidence references* (group, samples, run/result/finding ids), a *suggested next action* from a fixed per-rule text, and a **telemetry disclosure** (9). It carries `cause_status = not_investigated` until an investigation exists; then it links the `agent_runs` row and shows the Stage 11 labels (likely / hypothesis, never confirmed). No alert text is model-written.

**When rules run** (Q125): there is no scheduler in the codebase, so (i) event rules run in the ingestion transaction for the groups touched by the batch (cheap, indexed, bounded to those groups); (ii) internal rules run from the existing run/finding state changes (a call at the point a run reaches a terminal state and a finding is reopened, inside the same service functions, best effort: an evaluation error is logged and counted but never fails the run/finding transition); (iii) time-driven rules (`telemetry_gap`, and closing a window) are evaluated lazily whenever the alert list or telemetry status is read, idempotently under a per-project advisory lock, and by a `python -m sentinel_ai.cli evaluate-alerts` command for cron. A periodic worker job is deferred; until then a quiet, never-opened project may show a gap alert late, which is documented.

Caps: at most 200 open alerts per project (beyond that new alerts are counted into one `alert_overflow` alert), so a flood cannot bury the list.

### 7. Correlation (identifiers only; proximity is labelled as proximity)
Claimed `run_id`, `result_id`, `finding_id` are accepted as a link only if the record belongs to the **same project** (checked by one scoped query); otherwise the claim is stored as unverified and **never shown as a link**. Correlation is two-tier and labelled: `linked` (verified identifier) and `during_run` (the event's `received_at` falls inside a run's start/finish window in the same project and environment label `local`/`development`/`staging`; shown as "occurred while run X was active", never "caused by"). Trace ids stay opaque. A correlation never changes a finding's status, verification state or any run result: events are not verification evidence (finding states stay owned by `findings.ingest_scan` and the manual verification endpoint).

### 8. Failure-to-test loop (selective, user-triggered, text only)
1. An alert page offers **Investigate** and **Draft a regression test** (project `run` access; read-only and break-glass cannot, as in ADR-0010).
2. Both reuse the existing graphs (`investigation-v1`, `regression-v1`) with a new subject `alert_id` (the request accepts exactly one of `result_id`/`finding_id`/`alert_id`). Evidence offered to the model: the group's normalized message, up to 5 redacted samples, stack, verified correlated results/findings, and the telemetry disclosure, through the existing allow-list, excerpting, redaction and delimiter pipeline (new allowed kind `event_sample` for investigation and regression).
3. **Never automatic.** Nothing starts a model call because an alert fired (cost and prompt-exposure stay a person's decision, within ADR-0010 budgets).
4. **Eligibility for a regression draft** (deterministic, reasons returned): group has an `error_type` and a stack **or** a verified correlated failed result; at least 2 occurrences; project has an analysed source of a supported framework. Otherwise the response lists exactly what is missing ("no stack trace in reported events", "no analysed source"), so a missing context is explained, not guessed.
5. The proposal is a `regression_tests` row linked to the alert and group (`alert_id`, `event_group_id` added in Step 2's migration); it carries the existing code checks, risk flags and review warnings. **It is stored text.** Accepting records a decision and an audit event; it writes nothing to the source, commits nothing, opens no PR and starts no run (Q107 stays as built: confirm). Turning an accepted draft into a plan item remains a person's act through the normal plan approval path (Q119: proposal below).
6. "Failure reproduced / fix resolved" (blueprint 5.8 steps 7-9) is **not** claimed by this stage: it needs a run of an approved test, which is Stage 15 (reliability and regression verification). Stage 12 ends at the reviewed proposal.

### 9. Disclosure of missing telemetry
`GET /projects/{id}/telemetry-status` and the alert detail return a `telemetry` block built only from stored facts: ingestion enabled or not, active keys, last accepted event time, counts by level/environment, drop counts by reason in the last 24 h, share of samples with a stack, whether any trace ids were seen, whether run/result/finding links were ever verified, and fixed text for what Stage 12 cannot see (no traces resolved, no metrics, no logs below the floor, no third-party sources, forgeable external events). A project with no events shows "No application events have been received" rather than an empty, healthy-looking list.

### 10. Authorization and audit
Alert and group reads need project `read`; acknowledge, resolve, investigate, draft need `run`; ingest-key management, thresholds and the ingestion policy need `manage` (same policy machinery as ADR-0003, Q51). Break-glass grants are read-only. Every route resolves access through `project_id` (no id alone is proof). Alert rules, internal sources and the gateway never call authorization-bypassing code. Audit events: `ingest_key.create|revoke`, `observability.policy_change`, `alert.acknowledge|resolve|reopen` (with the actor and note), `alert.investigate`, `alert.regression_draft`, and `alert.create` written with a system actor and the rule name. High-volume ingestion itself is **not** audited per batch; counts are in `event_groups`/`event_buckets` and drop counters.

### 11. Retention (proposal; Q124)
Redacted samples 30 days; hourly buckets 30 days; groups and closed alerts 180 days after `last_seen`/closure; open alerts and their evidence references are kept while open; ingest keys' metadata 1 year after revocation; audit rows follow the existing rule (never deleted by application code). Settings `EVENT_SAMPLE_RETENTION_DAYS=30`, `EVENT_GROUP_RETENTION_DAYS=180`. Because no scheduler exists (Q70), Step 2 adds `cli purge-events` (batched deletes, dry-run flag, reports counts) and read paths ignore expired rows; running it periodically is an operator action until Stage 16.

## Data model (migration 0010, written in Step 2; names are the design, DDL follows the migration)
`ingest_keys` (project, key_id unique, key_hash, label, created_by, expires_at, revoked_at, last_used_at); `event_groups`, `event_buckets`, `events` (5); `alerts` (project, rule, rule_version, subject_key, group_id/run_id/result_id/finding_id nullable, severity, status `open|acknowledged|resolved`, occurrences, first/last seen, evidence JSON of ids and counts only, measured JSON, cause_status, agent_run_id, unique open alert per `(project, rule, subject_key)` by partial index); `alert_history` (append-only: created, acknowledged, resolved, reopened, recurrence, with actor and note; protected by the existing `forbid_mutation` pattern); `regression_tests` gains `alert_id` and `event_group_id`; `agent_runs.subject` accepts `alert`. CHECKs mirror the bounds above (levels, environments, hex formats, counts >= 0, status vocabulary, resolved needs `closed_at`). Every table carries `project_id` and every query joins through it. No secrets, raw payloads or prompts are stored.

## API (proposed, built stepwise; envelope and error codes as elsewhere)
`POST /ingest/v1/events` (key); `POST|GET|DELETE /projects/{id}/ingest-keys[/{key_id}]` (manage); `GET /projects/{id}/telemetry-status` (read); `GET /projects/{id}/event-groups[/{gid}]` (read; samples included in the detail); `GET /projects/{id}/alerts?status=&severity=&rule=` and `/alerts/{aid}` (read; evaluation of time rules happens here); `POST /projects/{id}/alerts/{aid}/acknowledge|resolve` `{note}` (run); `PUT /projects/{id}/policies/alert_thresholds|observability_ingest` (manage, existing policy route); investigation and regression drafts through the existing `POST /projects/{id}/agent-runs` with `alert_id`. Rate limits: ingestion per key as in (5); acknowledge/resolve and agent runs use the existing per-user limits.

## Threat model (summary; the full table goes into SECURITY_AND_SAFETY in Step 2)
| Threat | Control |
|---|---|
| Stolen or leaked ingest key | one-project write-only scope, hashed at rest, expiry, immediate revoke, per-key rate and daily quota, audited lifecycle; a thief can only add noise to that project |
| Forged or poisoned events (fake errors, fake "fix" signals) | events labelled as application-reported; they cannot change finding/run/verification state, cannot trigger model calls or runs, and alerts say "reported", not "confirmed" |
| Flooding / cardinality explosion / storage growth | batch and body caps, per-key rate, per-project daily quota, 5,000-group cap with overflow group, 20 samples per group, open-alert cap, retention |
| Secrets and personal data in logs | opt-in per project, redaction before storage, no raw persistence, key-name denylist, retention, UI limit text (Q113) |
| Prompt injection through log text | evidence filter + data delimiters + gateway redaction; model output validated (ADR-0010); investigations are user-triggered only |
| Stored XSS / injection via event text | plain-text rendering only, parameterized SQL, no templating of event text |
| Cross-project leakage | key and every query scoped by `project_id`; cross-project tests mandatory (an event, alert, group or key id from another project must 404) |
| False correlation misleading a developer | verified identifiers only; proximity labelled "occurred while"; no causal wording; unverified claims never rendered as links |
| Alert fatigue | fixed rules, dedup per subject, configurable thresholds within bounds, open-alert cap, grouped drops |
| Clock manipulation | rules use `received_at`; client timestamps are advisory |
| Rules failing silently | evaluation errors are counted and surfaced in the telemetry block ("evaluation errors in last 24 h"); a failure never fails ingestion's acceptance or a run transition |

## Test plan (summary per step)
Step 2: ingestion auth (missing/expired/revoked/other-project key identical 401; cookie ignored), schema bounds, redaction table tests incl. shared-pattern parity with the gateway redactor, caps/quotas/rate limit, no raw payload in DB or logs, migration up/down on a disposable DB. Step 3: normalization/fingerprint golden cases, threshold boundaries, dedup, baseline-less spike, recurrence reopening. Step 4: verified vs unverified correlation, cross-project claim ignored, `during_run` labelled, internal rules do not fail run transitions. Step 5: authorization matrix per route (read/run/manage/break-glass/none), acknowledge/resolve history and audit, lazy gap evaluation idempotence. Step 6: new subject through both graphs with the fake provider, eligibility reasons, text-only proposals, nothing run or committed, no automatic model call. Step 7: UI tests and axe. Step 8: full suites, lint, types, a focused security review.

## Alternatives considered
- **OTLP/OpenTelemetry now:** better standard, but needs a collector and trace storage design; Stage 13's job. Opaque trace ids keep the door open.
- **Pull from existing tools (Sentry, Loki, Datadog):** reuses what teams have but needs outbound credentials to third parties and per-vendor adapters; deferred (owner chose push-only).
- **Store every event:** simpler to query, unbounded cost and a larger secret-exposure surface; rejected for groups + buckets + capped samples.
- **Model decides what is an alert or how severe:** nondeterministic, costly, injectable; rejected (blueprint 7.6 says thresholds and counts stay deterministic).
- **Session-cookie auth for ingestion:** not usable from servers and would add a CSRF surface; rejected for scoped ingest keys.
- **Auto-investigate every alert:** rejected for cost and exposure; investigation is explicit.

## Consequences
New migration, a new credential type (needs ADR-0002 amendment once confirmed), a shared redaction module, two new graph subjects, a UI tab. No change to sandbox, approval or finding-state logic. Everything shipped in Stage 12 is fakeable offline; no external service is contacted.

## Implementation amendments (Steps 2-8, 2026-10-24)
Where the built system differs from the text above, the built system is described here.
- **Path.** Ingestion is `POST /api/v1/ingest/events` (the version is the API prefix, not a second `/v1`).
- **Event ids are not de-duplicated.** `event_id` is accepted and stored on a kept sample, but there is no 24-hour de-duplication table: a retried request can double count. The response counts say what was accepted.
- **Threshold bounds are constants in code**, not an organization policy key (`alert_threshold_bounds` was not built). Projects set values through `PUT /projects/{id}/policies/alert_thresholds` (manager), each inside the fixed range in `services/observability_policy.py`; an invalid stored value falls back to the default. The same route handles `observability_ingest`. Policy changes are audited by the existing `policy.update` event, not a separate `observability.policy_change`.
- **Recurrence reopens the original alert** (history action `reopened`, detail `rule: recurrence`, audit `alert.reopen`) instead of being a separate alert rule; the alert rules are `new_error_group`, `error_rate_spike`, `run_failed`, `finding_reopened`, `telemetry_gap`, `ingest_dropping` and `alert_overflow`.
- **`new_error_group`** fires when a group's total count reaches the threshold while `now - first_seen` is inside the window (exact, no sub-hour buckets needed). Buckets are hourly in UTC (computed in code, never by the database time zone) and feed only the spike rule; a baseline needs at least 6 prior hourly buckets.
- **`run_failed`** is raised when a run is finalized (`job_state.finalize_run`), from `failed`/`timed_out` status or failed/errored/timed-out results, in a savepoint so an alerting error never fails the run transition. Runs closed by other paths (for example the reconciler cancelling) are not alerted.
- **`ingest_dropping`** is raised at ingestion for quota and group-cap drops. Rate-limited requests are counted in `ingest_stats` (written at most once a minute per key, so rejected requests do no database work) but do not raise an alert.
- **Failed-authentication throttle** is per source address and in process (`INGEST_FAILED_AUTH_PER_MINUTE`, default 30). Behind a shared proxy address an attacker's bad keys can make that address answer 429 to valid senders until the minute passes (availability only; the 256-bit secret cannot be guessed). `X-Forwarded-For` is not trusted (Q136).
- **Shared redaction** lives in `core/text_redaction.py` (moved, not rewritten); `PromptRedactor` and `EventRedactor` both call it and a test asserts identical output. The secret-name patterns now bound the text around the secret-like word to 40 characters, because the unbounded form took seconds on an 8 kB run of word characters (a CPU denial of service for event ingestion and, in principle, prompts). Output on normal text is unchanged (all earlier redaction tests pass); a key name longer than 40 characters around the secret word is still redacted.
- **Samples** are ordered by an identity column (`events.seq`), so "first 5 and latest" is exact even when a batch shares one `received_at`.
- **Time rules** also have `python -m sentinel_ai.cli evaluate-alerts` (every project with ingestion on) and retention has `python -m sentinel_ai.cli purge-events [--dry-run]`; neither is scheduled by the application (Q125, Q70).
- **Failure-to-test:** `alert_id` is a third subject of the investigation and regression graphs. An alert with reported events is classified `reported_error` and may reach the model (user-triggered, existing budgets); an alert that is only a measurement is classified `no_failure_evidence` and never does; an alert that points at a result or finding uses that evidence. Regression eligibility for alerts is `agents/regression.alert_missing_evidence` (error type and stack, or a failed result with a failed case; at least 2 occurrences; a supported framework in the analysed source). Q119 is **not** implemented as proposed: accepting still needs `run` access and the requester may accept (see Q119).
- **Not built:** per-event de-duplication, organization-set threshold bounds, an event search or log browser, notifications, a periodic worker for time rules or retention, trace storage, `.env.example` entries for the new settings (outside the permitted paths, as in Q56), a browser check of the new screens.
