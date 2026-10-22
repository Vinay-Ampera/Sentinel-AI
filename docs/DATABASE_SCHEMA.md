# Database Schema

> Status: SKELETON. Real schema is Stage 2 work; do not assume any table exists.

## Entity groups (direction, plan §9)
Identity; Access (memberships, policies); Projects (sources, analysis snapshots); Planning (plans, planned tests, approvals); Execution (runs, batches, test cases, results, job events); Findings (events, verification attempts); Observability (alerts, anomalies); Artifacts (metadata + storage refs); Audit.

## Rules
Stable IDs, foreign keys, indexes, timestamps, explicit status enums/constraints; large artifacts outside rows; no raw secrets; authorization-scoped queries; versioned migrations only; retention policy defined before production; pgvector only if justified.

## TODO
Tables, relationships, indexes, ownership, retention, migration notes.
