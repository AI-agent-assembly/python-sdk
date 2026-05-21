from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class Decision(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DECISION_UNSPECIFIED: _ClassVar[Decision]
    ALLOW: _ClassVar[Decision]
    DENY: _ClassVar[Decision]
    PENDING: _ClassVar[Decision]
    REDACT: _ClassVar[Decision]

class ActionType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ACTION_UNSPECIFIED: _ClassVar[ActionType]
    LLM_CALL: _ClassVar[ActionType]
    TOOL_CALL: _ClassVar[ActionType]
    FILE_OPERATION: _ClassVar[ActionType]
    NETWORK_CALL: _ClassVar[ActionType]
    PROCESS_EXEC: _ClassVar[ActionType]
    AGENT_SPAWN: _ClassVar[ActionType]

class RiskTier(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RISK_UNSPECIFIED: _ClassVar[RiskTier]
    LOW: _ClassVar[RiskTier]
    MEDIUM: _ClassVar[RiskTier]
    HIGH: _ClassVar[RiskTier]
    CRITICAL: _ClassVar[RiskTier]
DECISION_UNSPECIFIED: Decision
ALLOW: Decision
DENY: Decision
PENDING: Decision
REDACT: Decision
ACTION_UNSPECIFIED: ActionType
LLM_CALL: ActionType
TOOL_CALL: ActionType
FILE_OPERATION: ActionType
NETWORK_CALL: ActionType
PROCESS_EXEC: ActionType
AGENT_SPAWN: ActionType
RISK_UNSPECIFIED: RiskTier
LOW: RiskTier
MEDIUM: RiskTier
HIGH: RiskTier
CRITICAL: RiskTier

class AgentId(_message.Message):
    __slots__ = ("org_id", "team_id", "agent_id")
    ORG_ID_FIELD_NUMBER: _ClassVar[int]
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    org_id: str
    team_id: str
    agent_id: str
    def __init__(self, org_id: _Optional[str] = ..., team_id: _Optional[str] = ..., agent_id: _Optional[str] = ...) -> None: ...

class Timestamp(_message.Message):
    __slots__ = ("unix_ms",)
    UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    unix_ms: int
    def __init__(self, unix_ms: _Optional[int] = ...) -> None: ...
