"""Unit tests for the `agent_assembly.models.agent` Pydantic models.

Covers the public data models re-exported from `agent_assembly.models`:
`AgentConfig`, `AgentState`, and `PolicyEvaluation`.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from agent_assembly.models import AgentConfig, AgentState, PolicyEvaluation


def test_models_package_reexports_public_symbols() -> None:
    import agent_assembly.models as models

    assert set(models.__all__) == {"AgentConfig", "AgentState", "PolicyEvaluation"}


def test_agent_config_defaults_applied_for_optional_fields() -> None:
    config = AgentConfig(agent_id="a-1", name="Researcher")

    assert config.agent_id == "a-1"
    assert config.name == "Researcher"
    assert config.description is None
    assert config.version == "0.1.0"
    assert isinstance(config.created_at, datetime)
    assert isinstance(config.updated_at, datetime)


def test_agent_config_accepts_explicit_overrides() -> None:
    stamp = datetime(2026, 1, 2, 3, 4, 5)
    config = AgentConfig(
        agent_id="a-2",
        name="Planner",
        description="plans things",
        version="2.5.0",
        created_at=stamp,
        updated_at=stamp,
    )

    assert config.description == "plans things"
    assert config.version == "2.5.0"
    assert config.created_at == stamp


def test_agent_config_requires_agent_id_and_name() -> None:
    with pytest.raises(ValidationError):
        AgentConfig(name="missing-id")  # type: ignore[call-arg]


def test_agent_state_defaults_to_idle_with_empty_metadata() -> None:
    state = AgentState(agent_id="a-1")

    assert state.status == "idle"
    assert state.last_activity is None
    assert state.metadata == {}


def test_agent_state_carries_metadata_and_activity() -> None:
    stamp = datetime(2026, 6, 18, 12, 0, 0)
    state = AgentState(
        agent_id="a-1",
        status="running",
        last_activity=stamp,
        metadata={"region": "us-east"},
    )

    assert state.status == "running"
    assert state.last_activity == stamp
    assert state.metadata["region"] == "us-east"


def test_policy_evaluation_allowed_decision() -> None:
    evaluation = PolicyEvaluation(action="send_email", allowed=True)

    assert evaluation.action == "send_email"
    assert evaluation.allowed is True
    assert evaluation.reason is None
    assert evaluation.policy_id is None


def test_policy_evaluation_denied_decision_records_reason_and_policy() -> None:
    evaluation = PolicyEvaluation(
        action="delete_db",
        allowed=False,
        reason="destructive action blocked",
        policy_id="pol-7",
    )

    assert evaluation.allowed is False
    assert evaluation.reason == "destructive action blocked"
    assert evaluation.policy_id == "pol-7"


def test_policy_evaluation_requires_action_and_allowed() -> None:
    with pytest.raises(ValidationError):
        PolicyEvaluation(action="x")  # type: ignore[call-arg]
