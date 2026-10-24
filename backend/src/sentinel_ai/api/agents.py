"""Agent workflow runs and regression proposals (Stage 11). Every route needs the role
capability AND project access; starting a run or deciding a proposal needs ``run`` access (a
break-glass grant is read-only and so cannot start a model call). Model use, budgets and
redaction are the gateway's; plans a workflow drafts go through the normal submit/approve path;
a regression proposal is text that is never written or run by Sentinel."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from sentinel_ai.api.deps import (
    get_db,
    request_context,
    require_permission,
    require_project_access,
)
from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.permissions import AccessLevel, Permission
from sentinel_ai.schemas.agents import (
    AgentRunOut,
    CreateAgentRunRequest,
    ProposalDecisionRequest,
    RegressionProposalOut,
)
from sentinel_ai.services import agent_workflows as service
from sentinel_ai.services import regression_proposals as proposals_service
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.auth import Principal

router = APIRouter(tags=["agent-runs"])

_VIEW = [Depends(require_permission(Permission.PROJECT_VIEW))]
_PLAN_ROLE = [Depends(require_permission(Permission.PLAN_AND_RUN))]
_READ = Depends(require_project_access(AccessLevel.READ))
_RUN = Depends(require_project_access(AccessLevel.RUN))
AGENT_RUNS_PER_MINUTE = 10


def _runtime(request: Request) -> service.Runtime:
    state = request.app.state
    return service.Runtime(state.llm_gateway, state.session_factory, state.settings)


@router.post("/projects/{project_id}/agent-runs", status_code=201, dependencies=_PLAN_ROLE)
def create_agent_run(
    project_id: uuid.UUID,
    body: CreateAgentRunRequest,
    request: Request,
    principal: Principal = _RUN,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> AgentRunOut:
    if not request.app.state.agent_limiter.allow(str(principal.user.id)):
        raise DomainError(429, "rate_limited", "Too many agent runs; try again shortly")
    rt, user, wf = _runtime(request), principal.user, body.workflow
    if wf == "planning":
        assert body.prompt is not None
        detail = service.run_planning(
            db, ctx, user, project_id, prompt=body.prompt, snapshot_id=body.snapshot_id, rt=rt
        )
    elif wf == "analysis":
        assert body.snapshot_id is not None
        detail = service.run_analysis(
            db, ctx, user, project_id, snapshot_id=body.snapshot_id, rt=rt
        )
    elif wf == "investigation":
        detail = service.run_investigation(
            db, ctx, user, project_id, result_id=body.result_id, finding_id=body.finding_id,
            alert_id=body.alert_id, rt=rt,
        )  # fmt: skip
    elif wf == "regression":
        detail = service.run_regression(
            db, ctx, user, project_id, result_id=body.result_id, finding_id=body.finding_id,
            alert_id=body.alert_id, rt=rt,
        )  # fmt: skip
    else:
        assert body.finding_id is not None and body.mode is not None
        detail = service.run_verification(
            db, ctx, user, project_id, finding_id=body.finding_id, mode=body.mode,
            run_id=body.run_id, summarize=body.summarize, rt=rt,
        )  # fmt: skip
    return AgentRunOut.from_detail(detail)


@router.get("/projects/{project_id}/agent-runs", dependencies=_VIEW)
def list_agent_runs(
    project_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    _: Principal = _READ,
    db: Session = Depends(get_db),
) -> dict[str, list[AgentRunOut]]:
    return {"items": [AgentRunOut.from_record(r) for r in service.list_runs(db, project_id, limit)]}


@router.get("/projects/{project_id}/agent-runs/{run_id}", dependencies=_VIEW)
def get_agent_run(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    _: Principal = _READ,
    db: Session = Depends(get_db),
) -> AgentRunOut:
    return AgentRunOut.from_detail(service.get_run(db, project_id, run_id))


@router.get("/projects/{project_id}/regression-proposals", dependencies=_VIEW)
def list_regression_proposals(
    project_id: uuid.UUID,
    status: Annotated[str | None, Query(pattern="^(proposed|accepted|rejected|verified)$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    _: Principal = _READ,
    db: Session = Depends(get_db),
) -> dict[str, list[RegressionProposalOut]]:
    rows = proposals_service.list_proposals(db, project_id, status, limit)
    return {"items": [RegressionProposalOut.from_record(p) for p in rows]}


@router.get("/projects/{project_id}/regression-proposals/{proposal_id}", dependencies=_VIEW)
def get_regression_proposal(
    project_id: uuid.UUID,
    proposal_id: uuid.UUID,
    _: Principal = _READ,
    db: Session = Depends(get_db),
) -> RegressionProposalOut:
    return RegressionProposalOut.from_record(
        proposals_service.get_proposal(db, project_id, proposal_id)
    )


@router.post(
    "/projects/{project_id}/regression-proposals/{proposal_id}/decision",
    dependencies=_PLAN_ROLE,
)
def decide_regression_proposal(
    project_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: ProposalDecisionRequest,
    principal: Principal = _RUN,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> RegressionProposalOut:
    record = proposals_service.decide(
        db, ctx, principal.user, project_id, proposal_id, decision=body.decision, note=body.note
    )
    return RegressionProposalOut.from_record(record)
