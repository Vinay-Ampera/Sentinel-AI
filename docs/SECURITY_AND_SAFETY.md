# Security and Safety

> Status: SKELETON from plan §5, §8. Permission matrix and threat model are undefined (OPEN_QUESTIONS Q5, Q6).

## Roles (summary)
- **Developer:** authorized projects; run/cancel/rerun permitted tests; inspect evidence; propose regression tests. Cannot bypass scope, policy, sandbox, or approvals.
- **Admin:** users, project access, policies, approvals within scope.
- **Super Admin:** platform-wide policy and privileged administration, fully audited.

## Rules
- Authorization on backend endpoints and in workers (revalidate before execution).
- Every project/run/artifact/finding/log is owner/team scoped.
- Destructive, intrusive, production, or high-risk tests need explicit approval.
- Audit sensitive actions and approval decisions.
- Never test public/production targets without authorization and documented scope.
- Secrets never in source, frontend env, logs, artifacts, or prompts.
- Scanner output is not "confirmed" without verification evidence.

## TODO
Permission matrix, auth/session design, data handling and retention, threat model, residual risks.
