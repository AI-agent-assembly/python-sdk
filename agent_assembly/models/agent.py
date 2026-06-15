"""Agent data models for the SDK."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """Configuration for an agent."""

    agent_id: str = Field(..., description="Unique identifier for the agent")
    name: str = Field(..., description="Human-readable name for the agent")
    description: Optional[str] = Field(None, description="Description of the agent")
    version: str = Field(default="0.1.0", description="Agent version")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")


class AgentState(BaseModel):
    """Current state of an agent."""

    agent_id: str = Field(..., description="Unique identifier for the agent")
    status: str = Field(default="idle", description="Current status of the agent")
    last_activity: Optional[datetime] = Field(None, description="Last activity timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional state metadata")


class PolicyEvaluation(BaseModel):
    """Result of a policy evaluation."""

    action: str = Field(..., description="Action that was evaluated")
    allowed: bool = Field(..., description="Whether the action is allowed")
    reason: Optional[str] = Field(None, description="Reason for the decision")
    policy_id: Optional[str] = Field(None, description="ID of the policy that made the decision")
