# Agent Workflows

> Status: SKELETON from plan §11. Implemented in Stage 11.

## Principle
Deterministic services first; agents only where interpretation adds value. LLM output never overrides authorization, approval, or sandbox policy. Outputs use validated structured schemas.

## Planned graphs
1. Analysis: validate input → deterministic discovery → optional LLM interpretation → persist.
2. Planning: load analysis → applicable capabilities → optional LLM proposals → policy/risk checks → plan review.
3. Execution: authorize → enqueue → worker → sandbox → persist (long-running work stays in workers).
4. Investigation: collect evidence → classify → optional analysis → propose cause/tests → human review.
5. Verification: load finding/fix → select checks → execute safely → compare evidence → update status with limitations.

## Cost controls
Filter/dedupe before calls; cache by source/version hash; focused excerpts; bounded tokens/retries/time/per-project cost; record model, usage, latency; keep secrets out of prompts.

## TODO
State schemas, node definitions, routing conditions, failure handling.
