import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class OpControlSignal(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    OP_CONTROL_SIGNAL_UNSPECIFIED: _ClassVar[OpControlSignal]
    OP_CONTROL_SIGNAL_PAUSE: _ClassVar[OpControlSignal]
    OP_CONTROL_SIGNAL_RESUME: _ClassVar[OpControlSignal]
    OP_CONTROL_SIGNAL_TERMINATE: _ClassVar[OpControlSignal]
OP_CONTROL_SIGNAL_UNSPECIFIED: OpControlSignal
OP_CONTROL_SIGNAL_PAUSE: OpControlSignal
OP_CONTROL_SIGNAL_RESUME: OpControlSignal
OP_CONTROL_SIGNAL_TERMINATE: OpControlSignal

class CheckActionRequest(_message.Message):
    __slots__ = ("agent_id", "credential_token", "trace_id", "span_id", "action_type", "context")
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    CREDENTIAL_TOKEN_FIELD_NUMBER: _ClassVar[int]
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    SPAN_ID_FIELD_NUMBER: _ClassVar[int]
    ACTION_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    agent_id: _common_pb2.AgentId
    credential_token: str
    trace_id: str
    span_id: str
    action_type: _common_pb2.ActionType
    context: ActionContext
    def __init__(self, agent_id: _Optional[_Union[_common_pb2.AgentId, _Mapping]] = ..., credential_token: _Optional[str] = ..., trace_id: _Optional[str] = ..., span_id: _Optional[str] = ..., action_type: _Optional[_Union[_common_pb2.ActionType, str]] = ..., context: _Optional[_Union[ActionContext, _Mapping]] = ...) -> None: ...

class ActionContext(_message.Message):
    __slots__ = ("llm_call", "tool_call", "file_op", "network_call", "process_exec")
    LLM_CALL_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALL_FIELD_NUMBER: _ClassVar[int]
    FILE_OP_FIELD_NUMBER: _ClassVar[int]
    NETWORK_CALL_FIELD_NUMBER: _ClassVar[int]
    PROCESS_EXEC_FIELD_NUMBER: _ClassVar[int]
    llm_call: LLMCallContext
    tool_call: ToolCallContext
    file_op: FileOpContext
    network_call: NetworkCallContext
    process_exec: ProcessExecContext
    def __init__(self, llm_call: _Optional[_Union[LLMCallContext, _Mapping]] = ..., tool_call: _Optional[_Union[ToolCallContext, _Mapping]] = ..., file_op: _Optional[_Union[FileOpContext, _Mapping]] = ..., network_call: _Optional[_Union[NetworkCallContext, _Mapping]] = ..., process_exec: _Optional[_Union[ProcessExecContext, _Mapping]] = ...) -> None: ...

class LLMCallContext(_message.Message):
    __slots__ = ("model", "prompt_tokens", "contains_pii")
    MODEL_FIELD_NUMBER: _ClassVar[int]
    PROMPT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    CONTAINS_PII_FIELD_NUMBER: _ClassVar[int]
    model: str
    prompt_tokens: int
    contains_pii: bool
    def __init__(self, model: _Optional[str] = ..., prompt_tokens: _Optional[int] = ..., contains_pii: bool = ...) -> None: ...

class ToolCallContext(_message.Message):
    __slots__ = ("tool_name", "tool_source", "args_json", "target_url")
    TOOL_NAME_FIELD_NUMBER: _ClassVar[int]
    TOOL_SOURCE_FIELD_NUMBER: _ClassVar[int]
    ARGS_JSON_FIELD_NUMBER: _ClassVar[int]
    TARGET_URL_FIELD_NUMBER: _ClassVar[int]
    tool_name: str
    tool_source: str
    args_json: bytes
    target_url: str
    def __init__(self, tool_name: _Optional[str] = ..., tool_source: _Optional[str] = ..., args_json: _Optional[bytes] = ..., target_url: _Optional[str] = ...) -> None: ...

class FileOpContext(_message.Message):
    __slots__ = ("operation", "path", "is_sensitive_path")
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    IS_SENSITIVE_PATH_FIELD_NUMBER: _ClassVar[int]
    operation: str
    path: str
    is_sensitive_path: bool
    def __init__(self, operation: _Optional[str] = ..., path: _Optional[str] = ..., is_sensitive_path: bool = ...) -> None: ...

class NetworkCallContext(_message.Message):
    __slots__ = ("host", "port", "protocol", "in_allowlist")
    HOST_FIELD_NUMBER: _ClassVar[int]
    PORT_FIELD_NUMBER: _ClassVar[int]
    PROTOCOL_FIELD_NUMBER: _ClassVar[int]
    IN_ALLOWLIST_FIELD_NUMBER: _ClassVar[int]
    host: str
    port: int
    protocol: str
    in_allowlist: bool
    def __init__(self, host: _Optional[str] = ..., port: _Optional[int] = ..., protocol: _Optional[str] = ..., in_allowlist: bool = ...) -> None: ...

class ProcessExecContext(_message.Message):
    __slots__ = ("command", "args")
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    command: str
    args: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, command: _Optional[str] = ..., args: _Optional[_Iterable[str]] = ...) -> None: ...

class CheckActionResponse(_message.Message):
    __slots__ = ("decision", "reason", "policy_rule", "approval_id", "redact", "decision_latency_us")
    DECISION_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    POLICY_RULE_FIELD_NUMBER: _ClassVar[int]
    APPROVAL_ID_FIELD_NUMBER: _ClassVar[int]
    REDACT_FIELD_NUMBER: _ClassVar[int]
    DECISION_LATENCY_US_FIELD_NUMBER: _ClassVar[int]
    decision: _common_pb2.Decision
    reason: str
    policy_rule: str
    approval_id: str
    redact: RedactInstructions
    decision_latency_us: int
    def __init__(self, decision: _Optional[_Union[_common_pb2.Decision, str]] = ..., reason: _Optional[str] = ..., policy_rule: _Optional[str] = ..., approval_id: _Optional[str] = ..., redact: _Optional[_Union[RedactInstructions, _Mapping]] = ..., decision_latency_us: _Optional[int] = ...) -> None: ...

class RedactInstructions(_message.Message):
    __slots__ = ("rules",)
    RULES_FIELD_NUMBER: _ClassVar[int]
    rules: _containers.RepeatedCompositeFieldContainer[RedactRule]
    def __init__(self, rules: _Optional[_Iterable[_Union[RedactRule, _Mapping]]] = ...) -> None: ...

class RedactRule(_message.Message):
    __slots__ = ("field_path", "replacement")
    FIELD_PATH_FIELD_NUMBER: _ClassVar[int]
    REPLACEMENT_FIELD_NUMBER: _ClassVar[int]
    field_path: str
    replacement: str
    def __init__(self, field_path: _Optional[str] = ..., replacement: _Optional[str] = ...) -> None: ...

class BatchCheckRequest(_message.Message):
    __slots__ = ("requests",)
    REQUESTS_FIELD_NUMBER: _ClassVar[int]
    requests: _containers.RepeatedCompositeFieldContainer[CheckActionRequest]
    def __init__(self, requests: _Optional[_Iterable[_Union[CheckActionRequest, _Mapping]]] = ...) -> None: ...

class BatchCheckResponse(_message.Message):
    __slots__ = ("responses",)
    RESPONSES_FIELD_NUMBER: _ClassVar[int]
    responses: _containers.RepeatedCompositeFieldContainer[CheckActionResponse]
    def __init__(self, responses: _Optional[_Iterable[_Union[CheckActionResponse, _Mapping]]] = ...) -> None: ...

class OpControlSubscribeRequest(_message.Message):
    __slots__ = ("agent_id",)
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    agent_id: _common_pb2.AgentId
    def __init__(self, agent_id: _Optional[_Union[_common_pb2.AgentId, _Mapping]] = ...) -> None: ...

class OpControlMessage(_message.Message):
    __slots__ = ("op_id", "signal", "sequence")
    OP_ID_FIELD_NUMBER: _ClassVar[int]
    SIGNAL_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    op_id: str
    signal: OpControlSignal
    sequence: int
    def __init__(self, op_id: _Optional[str] = ..., signal: _Optional[_Union[OpControlSignal, str]] = ..., sequence: _Optional[int] = ...) -> None: ...
