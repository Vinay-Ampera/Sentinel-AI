# ADR-0003: Plan approval policy, plan freezing and target gating

- Status: Accepted (Stage 6, 2026-10-22; owner review pending)
- Context: Stage 6 must let users see a plan before anything runs, route risky work to humans, and keep production blocked by default. Plans can come from automatic recommendation, a prompt, or developers; a model may later help (Stage 11) but must never be able to bypass authorization, approval or sandbox policy.

## Decisions
1. **Catalog, not commands.** A plan is a list of entries from a deterministic catalog (`check_catalog.py`) with fixed category, tool, base risk, prerequisites and expected evidence. Requests can select entries and pass a few validated parameters; they cannot carry commands, risk levels or approval flags. Prompt mode is keyword selection until Stage 11, which will produce the same structure and go through the same catalog.
2. **Risk is derived.** Remote targets raise risk (never below medium; active checks high). High/critical always need approval (code floor and DB CHECK); policy may add levels but never remove them.
3. **Plan-level approval.** One approval per submitted plan at the plan's highest risk. A plan with nothing needing a human is approved automatically and audited. Per-test approvals are not used (the schema column stays for later).
4. **Freeze and bind.** Submit freezes the plan (DB triggers) and stores a SHA-256 of the reviewed content and the policy snapshot; a decision is rejected (`plan_changed`) if the content no longer hashes to it. Only execution status can change afterwards. A DB trigger lets a run reference only an approved plan of the same project.
5. **Authority in one module, from grants not hierarchy (amended after the access review).** `services/policy.py`: an approver needs an explicit project grant, is never the requester, and (high/critical) holds an organization-allowed role; the project's designated approvers decide, or its managers if none are designated. The project manager (any role) controls allowed risk levels, approval levels and approvers within organization bounds. Production authorization stays Super Admin + global flag + grant + reason + 24 h cap. Replaces the earlier "Admin/Super Admin approve high risk" and "developer delegation" rules.
7. **No implicit project access for any role.** Super Admin no longer sees every project; Admin and Super Admin need a grant like everyone else, so plans, approvals and (later) runs, results and logs are isolated per project.
6. **Target authorization.** Remote dev/staging URLs need an approved, time-boxed authorization (risk levels, path prefixes, methods) checked at plan time, at submit and by the worker. Hosts come from the source. Authorizations are decided through the same approvals endpoint.

## Consequences
- Planning is honest about limits: statuses planned / skipped / deferred / blocked each carry a reason, and the API states `execution_available: false` until runners exist.
- The Stage 7 worker must re-run `gate_reason`, set `test_runs.plan_id` to the approved plan, and treat revocation/expiry as blocking.
- Rejected alternatives: letting a model assign risk (violates the safety rule); per-test approvals (more states, little value now); editing approved plans in place (breaks audit binding).

## Amendment 2026-10-23 (owner decisions Q47-Q51)
- **Break-glass** (Q47): temporary, read-only, justified, audited Super Admin access to a single project, implemented as its own table (migration 0004) rather than a membership, so it can expire, is never a "grant" for decisions, and cannot be edited or extended.
- **Decisions need explicit access** (Q48): production authorization and every approval use explicit grants only.
- **Developers and high risk** (Q49): excluded by default; only an organization-level setting by a Super Admin adds them, and project grant and non-requester rules still apply.
- **No self-approval** (Q50) at every risk level; the requester may only withdraw. **Project managers** manage project risk policy within organization limits (Q51).

