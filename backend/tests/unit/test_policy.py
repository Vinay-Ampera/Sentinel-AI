import uuid

import pytest

from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.permissions import AccessLevel
from sentinel_ai.services.check_catalog import CATALOG, RISK_DEFINITIONS, RISK_ORDER
from sentinel_ai.services.policy import (
    EffectivePolicy,
    authorization_decision_denial,
    eligibility_denial,
    merge,
    requires_approval,
    validate_value,
)

DEFAULTS = merge({}, {})
ME, OTHER = uuid.uuid4(), uuid.uuid4()


def test_defaults_block_production_and_require_high_risk_approval() -> None:
    assert DEFAULTS.production_allowed is False
    assert DEFAULTS.approval_required == {"high", "critical"}
    assert DEFAULTS.allowed_risk == set(RISK_ORDER)
    assert DEFAULTS.high_risk_roles == {"admin", "super_admin"}
    assert DEFAULTS.approvers == {}


def test_high_and_critical_always_need_approval_whatever_the_policy() -> None:
    assert requires_approval("high", False, DEFAULTS)
    assert not requires_approval("low", False, DEFAULTS)
    assert requires_approval("low", True, DEFAULTS)  # intrusive / custom checks
    assert merge({"approval_required_risk_levels": []}, {}).approval_required == {
        "high",
        "critical",
    }


def test_project_policy_can_only_be_stricter() -> None:
    g_allow = {"production_testing": {"allowed": True}}
    assert merge(g_allow, {}).production_allowed is True
    assert merge(g_allow, {"production_testing": {"allowed": False}}).production_allowed is False
    assert merge({}, {"production_testing": {"allowed": True}}).production_allowed is False
    stricter = merge({}, {"approval_required_risk_levels": ["medium"]})
    assert stricter.approval_required == {"medium", "high", "critical"}
    # Allowed levels intersect: a project narrows the organization's list, never widens it.
    both = merge(
        {"allowed_risk_levels": ["low", "medium"]}, {"allowed_risk_levels": ["low", "high"]}
    )
    assert both.allowed_risk == {"low"}
    assert merge({}, {"allowed_risk_levels": ["low", "medium"]}).allowed_risk == {"low", "medium"}


@pytest.mark.parametrize("bad", [None, "yes", 1, [], {"allowed": "true"}, {"allowed": 1}, {"x": 1}])
def test_malformed_production_values_fall_back_to_blocked(bad: object) -> None:
    assert merge({"production_testing": bad}, {}).production_allowed is False


def test_malformed_restrictions_fall_back_to_the_strictest_reading() -> None:
    p = merge(
        {"approval_required_risk_levels": "all", "allowed_risk_levels": "everything",
         "high_risk_approver_roles": ["janitor"]},
        {"allowed_risk_levels": [], "risk_approvers": "everyone"},
    )  # fmt: skip
    assert p.approval_required == {"high", "critical"}
    assert p.allowed_risk == {"low"}
    assert p.high_risk_roles == {"super_admin"}  # unknown role -> strictest
    assert p.approvers == {}


def decide(
    role: str,
    risk: str,
    *,
    level: AccessLevel = AccessLevel.MANAGE,
    requester: bool = False,
    user: uuid.UUID = ME,
    policy: EffectivePolicy = DEFAULTS,
):  # type: ignore[no-untyped-def]
    return eligibility_denial(
        role=role, user_id=user, risk=risk, is_requester=requester, level=level, policy=policy
    )


def test_nobody_approves_their_own_request_at_any_risk_or_role() -> None:
    for role in ("developer", "admin", "super_admin"):
        for risk in RISK_ORDER:
            assert decide(role, risk, requester=True) is not None


def test_default_approvers_are_project_managers_not_a_role_hierarchy() -> None:
    # Low/medium: whoever manages the project, whatever their role (a Developer owner too).
    assert decide("developer", "medium") is None
    assert decide("developer", "medium", level=AccessLevel.RUN) is not None
    assert decide("developer", "medium", level=AccessLevel.READ) is not None
    # Being an Admin or Super Admin adds nothing without project management access.
    assert decide("admin", "medium", level=AccessLevel.RUN) is not None
    assert decide("super_admin", "medium", level=AccessLevel.READ) is not None
    assert decide("admin", "medium") is None


def test_high_risk_is_bounded_by_organization_roles_and_project_access() -> None:
    assert decide("admin", "high") is None and decide("super_admin", "critical") is None
    assert decide("developer", "high") is not None  # org policy: role never approves high risk
    assert decide("admin", "high", level=AccessLevel.RUN) is not None  # role alone is not enough
    narrowed = merge({"high_risk_approver_roles": ["super_admin"]}, {})
    assert decide("admin", "high", policy=narrowed) is not None
    assert decide("super_admin", "high", policy=narrowed) is None
    # Developers approve high risk only through an explicit organization-level setting,
    # and even then only with project access and never their own request.
    opted_in = merge({"high_risk_approver_roles": ["developer", "admin", "super_admin"]}, {})
    assert decide("developer", "high", policy=opted_in) is None
    assert decide("developer", "high", level=AccessLevel.RUN, policy=opted_in) is not None
    assert decide("developer", "critical", requester=True, policy=opted_in) is not None
    assert merge({"high_risk_approver_roles": ["developer"]}, {}).high_risk_roles == {"developer"}


def test_project_designation_overrides_the_manager_default_within_org_bounds() -> None:
    designate = merge({}, {"risk_approvers": {"medium": [str(OTHER)], "high": [str(OTHER)]}})
    # Designated: eligible at read access, any role for medium ...
    assert (
        decide("developer", "medium", level=AccessLevel.READ, user=OTHER, policy=designate) is None
    )
    # ... but the project manager who did not designate themselves is now excluded.
    assert decide("developer", "medium", user=ME, policy=designate) is not None
    # High risk still needs an org-allowed role even if designated.
    assert (
        decide("developer", "high", level=AccessLevel.READ, user=OTHER, policy=designate)
        is not None
    )
    assert decide("admin", "high", level=AccessLevel.READ, user=OTHER, policy=designate) is None
    # Levels without a designation keep the default.
    assert decide("developer", "low", user=ME, policy=designate) is None


def test_authorization_decision_authority() -> None:
    def auth(
        role: str,
        env: str,
        *,
        risk: str = "medium",
        requester: bool = False,
        level: AccessLevel = AccessLevel.MANAGE,
        policy: EffectivePolicy = DEFAULTS,
    ):  # type: ignore[no-untyped-def]
        return authorization_decision_denial(
            role=role, user_id=ME, environment=env, risk=risk,
            is_requester=requester, level=level, policy=policy,
        )  # fmt: skip

    assert auth("admin", "staging") is None
    assert auth("developer", "staging") is not None  # org policy: remote targets are Admin's
    assert auth("admin", "staging", level=AccessLevel.RUN) is not None  # needs project management
    assert auth("admin", "staging", requester=True) is not None
    blocked = auth("super_admin", "production")
    assert blocked is not None and blocked.code == "policy_blocked"
    allowed = merge({"production_testing": {"allowed": True}}, {})
    assert auth("admin", "production", policy=allowed) is not None  # Super Admin only
    assert auth("super_admin", "production", policy=allowed) is None
    assert auth("super_admin", "production", requester=True, policy=allowed) is not None


def test_policy_value_validation_by_scope() -> None:
    assert validate_value("production_testing", {"allowed": False}, project_scope=False) == {
        "allowed": False
    }
    assert validate_value("approval_required_risk_levels", ["high", "low"], project_scope=True) == [
        "low",
        "high",
    ]
    good = {"high": [str(OTHER)]}
    assert validate_value("risk_approvers", good, project_scope=True) == good
    for key, value, project in [
        ("production_testing", True, False),
        ("production_testing", {"allowed": True, "extra": 1}, False),
        ("approval_required_risk_levels", ["extreme"], True),
        ("allowed_risk_levels", [], True),  # would block everything
        ("high_risk_approver_roles", ["janitor"], False),
        ("high_risk_approver_roles", [], False),  # would leave nobody able to approve
        ("high_risk_approver_roles", ["admin"], True),  # organization key, not a project key
        ("risk_approvers", {"high": ["not-a-uuid"]}, True),
        ("risk_approvers", {"extreme": [str(OTHER)]}, True),
        ("risk_approvers", {"high": [str(OTHER)] * 2}, True),  # duplicates
        ("risk_approvers", {"low": [str(uuid.uuid4()) for _ in range(11)]}, True),
        ("risk_approvers", [str(OTHER)], True),
        ("risk_approvers", good, False),  # a project key, not an organization key
        ("llm_limits", {"max_tokens_per_run": 1}, False),
        ("../../etc", [], False),
    ]:
        with pytest.raises(DomainError) as err:
            validate_value(key, value, project_scope=project)
        assert err.value.status_code == 422, (key, value)


def test_catalog_risk_levels_match_their_definitions() -> None:
    """Risk is defined by behaviour, so the rules below must hold for every catalog entry."""
    assert set(RISK_DEFINITIONS) == set(RISK_ORDER)
    for spec in CATALOG.values():
        idx = RISK_ORDER.index(spec.base_risk)
        if spec.active_on_target:
            assert idx >= 1, spec.check_id  # interacting with a target is never "low"
        if spec.needs_egress:
            assert idx >= 1, spec.check_id  # network egress is never "low"
        if spec.always_requires_approval:
            assert idx >= 2, spec.check_id  # always-approval checks are high or critical
        assert spec.base_risk != "critical", spec.check_id  # reserved
    intrusive = {"zap_active", "load_basic", "agent_tool_abuse", "custom_script"}
    assert {c for c, s in CATALOG.items() if s.always_requires_approval} == intrusive
