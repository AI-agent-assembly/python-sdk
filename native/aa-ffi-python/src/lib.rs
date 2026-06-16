//! Thin pyo3 shim over `aa-sdk-client`.
//!
//! Per ADR 0002 (Epic AAASM-2552), the runtime-client logic — UDS transport,
//! IPC wire codec, and the `AssemblyClient` lifecycle — lives once in the
//! shared `aa-sdk-client` crate. This binding is a thin pyo3 shim: ergonomic
//! API, type translation, and event capture. It holds **no** security
//! authority: the advisory, best-effort credential preflight is provided by
//! `aa-sdk-client`, and `aa-runtime` re-scans every event authoritatively.
//!
//! Approval is server-side (see the ADR trust model), so the binding does not
//! perform a synchronous approval round-trip; event reporting is
//! fire-and-forget over the shared client. The binding does expose a
//! synchronous, **advisory** `query_policy` over the same client: it asks the
//! runtime for a decision but fails *open* (returns `allow`) whenever the
//! runtime is unreachable or slow, because the runtime / proxy / eBPF layers
//! remain authoritative.

use aa_core::AuditEntry;
use aa_proto::assembly::audit::v1::AuditEvent;
use aa_proto::assembly::audit::v1::CallStackNode as ProtoCallStackNode;
use aa_proto::assembly::common::v1::ActionType;
use aa_proto::assembly::common::v1::AgentId;
use aa_proto::assembly::common::v1::Decision;
use aa_proto::assembly::policy::v1::action_context::Action as ProtoAction;
use aa_proto::assembly::policy::v1::{
    ActionContext, CheckActionRequest, CheckActionResponse, ToolCallContext,
};
use aa_sdk_client::ipc::spawn_ipc_thread;
use aa_sdk_client::{AssemblyClient, AssemblyConfig, SdkClientError};
use prost::Message;
use pyo3::exceptions::PyRuntimeError;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBytes, PyDict, PyList, PyModule};

#[pyclass(module = "agent_assembly._core", from_py_object)]
#[derive(Clone)]
struct GovernanceEvent {
    #[pyo3(get)]
    payload_json: String,
    audit_entry: AuditEntry,
}

#[pymethods]
impl GovernanceEvent {
    #[new]
    fn new(payload_json: String) -> PyResult<Self> {
        let audit_entry = serde_json::from_str::<AuditEntry>(&payload_json).map_err(|error| {
            PyValueError::new_err(format!(
                "GovernanceEvent payload must be serialized aa_core::AuditEntry JSON: {error}"
            ))
        })?;
        Ok(Self {
            payload_json,
            audit_entry,
        })
    }
}

/// Handle to an Agent Assembly runtime session.
///
/// Thin wrapper over [`aa_sdk_client::AssemblyClient`]: the UDS transport, wire
/// codec, and background IPC thread all live in `aa-sdk-client`. This type only
/// translates the Python surface (`connect` / `send_event` / `close`) onto the
/// shared client.
#[pyclass(module = "agent_assembly._core")]
struct RuntimeClient {
    #[pyo3(get)]
    socket_path: String,
    client: AssemblyClient,
}

#[pymethods]
impl RuntimeClient {
    /// Connect to `aa-runtime` over the given Unix domain socket path.
    ///
    /// Spawns the shared client's background IPC thread and returns a handle.
    /// Event reporting is fire-and-forget; a failed connection surfaces on a
    /// later `send_event` rather than here.
    #[staticmethod]
    fn connect(socket_path: String) -> PyResult<Self> {
        let config = AssemblyConfig {
            agent_id: String::new(),
            socket_path: Some(socket_path.clone()),
        };
        let handle = spawn_ipc_thread(config.resolve_socket_path()).map_err(|error| {
            PyRuntimeError::new_err(format!("failed to start runtime IPC thread: {error}"))
        })?;
        Ok(Self {
            socket_path,
            client: AssemblyClient::new(handle, Vec::new()),
        })
    }

    /// Ship a captured governance event to the runtime (fire-and-forget).
    ///
    /// The event payload passes through `aa-sdk-client`'s advisory preflight
    /// before the wire; the runtime re-scans authoritatively regardless.
    fn send_event(&self, py: Python<'_>, event: GovernanceEvent) -> PyResult<()> {
        let event_type = format!("{:?}", event.audit_entry.event_type());
        let details = event.payload_json;
        // Release the GIL while delegating: aa-sdk-client uses a bounded channel
        // with a blocking send, so under backpressure this can park the calling
        // thread — holding the GIL there would stall every other Python thread.
        py.detach(move || self.client.report_event(event_type, details))
            .map_err(map_sdk_error)
    }

    /// Synchronously ask the runtime for a policy decision on an action.
    ///
    /// Builds a `CheckActionRequest` from the supplied identity and action
    /// fields, ships it over the shared client, and blocks for the runtime's
    /// `CheckActionResponse` (the shared client caps this at a 5 s timeout).
    /// Returns a dict `{"decision": <str>, "reason": <str>}` where the decision
    /// is one of `"allow"`, `"deny"`, `"pending"`, `"redact"`, or
    /// `"unspecified"`.
    ///
    /// **Fail-open:** the SDK layer is advisory, never authoritative. When the
    /// runtime is unreachable or does not answer in time — the shared client
    /// returns [`SdkClientError::QueryFailed`] on timeout / mid-query
    /// disconnect, or [`SdkClientError::ChannelClosed`] when the IPC connection
    /// never came up (e.g. the runtime socket is absent) — this returns a
    /// non-deny `{"decision": "allow", "reason": <why>}` so a slow or absent
    /// runtime can never block the caller; the runtime / proxy / eBPF layers
    /// still enforce.
    #[pyo3(signature = (agent_id, action_type, tool_name=None, tool_args_json=None))]
    fn query_policy(
        &self,
        py: Python<'_>,
        agent_id: String,
        action_type: String,
        tool_name: Option<String>,
        tool_args_json: Option<String>,
    ) -> PyResult<Py<PyAny>> {
        let context = tool_name.map(|name| ActionContext {
            action: Some(ProtoAction::ToolCall(ToolCallContext {
                tool_name: name,
                args_json: tool_args_json.unwrap_or_default().into_bytes(),
                ..Default::default()
            })),
        });
        let request = CheckActionRequest {
            agent_id: Some(AgentId {
                org_id: String::new(),
                team_id: String::new(),
                agent_id,
            }),
            action_type: action_type_from_str(&action_type),
            context,
            ..Default::default()
        };

        // Release the GIL while blocking on the runtime round-trip so other
        // Python threads keep running during the (up to 5 s) wait.
        let outcome = py.detach(move || self.client.query_policy(request));

        let response = match outcome {
            Ok(response) => response,
            // Fail-open: an unreachable or slow runtime must never read as a
            // deny. QueryFailed = timeout / mid-query disconnect; ChannelClosed
            // = the IPC connection never came up. Synthesize an allow with the
            // reason so callers can still log it.
            Err(SdkClientError::QueryFailed | SdkClientError::ChannelClosed) => {
                CheckActionResponse {
                    decision: Decision::Allow as i32,
                    reason: "runtime unreachable; fail-open allow".to_string(),
                    ..Default::default()
                }
            }
            Err(error) => return Err(map_sdk_error(error)),
        };

        let result = PyDict::new(py);
        result.set_item("decision", policy_decision_to_str(response.decision))?;
        result.set_item("reason", response.reason)?;
        Ok(result.into_any().unbind())
    }

    /// Shut down the background IPC thread. Idempotent.
    fn close(&self, py: Python<'_>) {
        // Release the GIL while the shared client joins the background thread.
        py.detach(|| {
            let _ = self.client.shutdown();
        });
    }
}

fn map_sdk_error(error: SdkClientError) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}

fn action_type_from_str(value: &str) -> i32 {
    match value {
        "llm_call" => ActionType::LlmCall as i32,
        "tool_call" => ActionType::ToolCall as i32,
        "file_op" | "file_operation" => ActionType::FileOperation as i32,
        "network_call" => ActionType::NetworkCall as i32,
        "process_exec" => ActionType::ProcessExec as i32,
        "agent_spawn" => ActionType::AgentSpawn as i32,
        "tool_result" => ActionType::ToolResult as i32,
        _ => ActionType::ActionUnspecified as i32,
    }
}

fn action_type_to_str(value: i32) -> &'static str {
    match ActionType::try_from(value).unwrap_or(ActionType::ActionUnspecified) {
        ActionType::LlmCall => "llm_call",
        ActionType::ToolCall => "tool_call",
        ActionType::FileOperation => "file_op",
        ActionType::NetworkCall => "network_call",
        ActionType::ProcessExec => "process_exec",
        ActionType::AgentSpawn => "agent_spawn",
        ActionType::ToolResult => "tool_result",
        ActionType::ActionUnspecified => "",
    }
}

fn decision_from_str(value: &str) -> i32 {
    match value {
        "allow" => Decision::Allow as i32,
        "deny" => Decision::Deny as i32,
        "pending" => Decision::Pending as i32,
        "redact" => Decision::Redact as i32,
        _ => Decision::Unspecified as i32,
    }
}

fn audit_event_from_py(event: &Bound<'_, PyAny>) -> PyResult<AuditEvent> {
    let event_id = event.getattr("event_id")?.extract::<String>()?;
    let agent_id_str = event.getattr("agent_id")?.extract::<String>()?;
    let action_type_str = event.getattr("action_type")?.extract::<String>()?;
    let decision_str = event.getattr("decision")?.extract::<String>()?;
    let trace_id = event.getattr("trace_id")?.extract::<String>()?;
    let span_id = event.getattr("span_id")?.extract::<String>()?;
    let parent_span_id = event.getattr("parent_span_id")?.extract::<String>()?;
    let labels = event
        .getattr("labels")?
        .extract::<std::collections::HashMap<String, String>>()?;
    let call_stack_py = event.getattr("call_stack")?;
    let mut call_stack = Vec::new();
    for node in call_stack_py.try_iter()? {
        call_stack.push(call_stack_node_from_py(&node?)?);
    }
    Ok(AuditEvent {
        event_id,
        agent_id: Some(AgentId {
            org_id: String::new(),
            team_id: String::new(),
            agent_id: agent_id_str,
        }),
        action_type: action_type_from_str(&action_type_str),
        decision: decision_from_str(&decision_str),
        trace_id,
        span_id,
        parent_span_id,
        labels,
        call_stack,
        ..Default::default()
    })
}

fn audit_event_to_py(py: Python<'_>, event: &AuditEvent) -> PyResult<Py<PyAny>> {
    let types_module = PyModule::import(py, "agent_assembly.types")?;
    let cls = types_module.getattr("AuditEvent")?;
    let kwargs = PyDict::new(py);
    kwargs.set_item("event_id", &event.event_id)?;
    let agent_id_str = event
        .agent_id
        .as_ref()
        .map(|id| id.agent_id.clone())
        .unwrap_or_default();
    kwargs.set_item("agent_id", agent_id_str)?;
    kwargs.set_item("action_type", action_type_to_str(event.action_type))?;
    kwargs.set_item("decision", decision_to_str(event.decision))?;
    kwargs.set_item("trace_id", &event.trace_id)?;
    kwargs.set_item("span_id", &event.span_id)?;
    kwargs.set_item("parent_span_id", &event.parent_span_id)?;
    let labels = PyDict::new(py);
    for (k, v) in &event.labels {
        labels.set_item(k, v)?;
    }
    kwargs.set_item("labels", labels)?;
    let call_stack = PyList::empty(py);
    for node in &event.call_stack {
        call_stack.append(call_stack_node_to_py(py, node)?)?;
    }
    kwargs.set_item("call_stack", call_stack)?;
    Ok(cls.call((), Some(&kwargs))?.unbind())
}

fn call_stack_node_from_py(node: &Bound<'_, PyAny>) -> PyResult<ProtoCallStackNode> {
    let id = node.getattr("id")?.extract::<String>()?;
    let kind = node.getattr("kind")?.extract::<String>()?;
    let label = node.getattr("label")?.extract::<String>()?;
    let latency_ms = node
        .getattr("latency_ms")?
        .extract::<Option<i64>>()?
        .unwrap_or(0);
    let children_py = node.getattr("children")?;
    let mut children = Vec::new();
    for child in children_py.try_iter()? {
        children.push(call_stack_node_from_py(&child?)?);
    }
    Ok(ProtoCallStackNode {
        id,
        kind,
        label,
        latency_ms,
        children,
    })
}

fn call_stack_node_to_py(py: Python<'_>, node: &ProtoCallStackNode) -> PyResult<Py<PyAny>> {
    let types_module = PyModule::import(py, "agent_assembly.types")?;
    let cls = types_module.getattr("CallStackNode")?;
    let kwargs = PyDict::new(py);
    kwargs.set_item("id", &node.id)?;
    kwargs.set_item("kind", &node.kind)?;
    kwargs.set_item("label", &node.label)?;
    let latency: Option<i64> = if node.latency_ms == 0 {
        None
    } else {
        Some(node.latency_ms)
    };
    kwargs.set_item("latency_ms", latency)?;
    let children = PyList::empty(py);
    for child in &node.children {
        children.append(call_stack_node_to_py(py, child)?)?;
    }
    kwargs.set_item("children", children)?;
    Ok(cls.call((), Some(&kwargs))?.unbind())
}

fn decision_to_str(value: i32) -> &'static str {
    match Decision::try_from(value).unwrap_or(Decision::Unspecified) {
        Decision::Allow => "allow",
        Decision::Deny => "deny",
        Decision::Pending => "pending",
        Decision::Redact => "redact",
        Decision::Unspecified => "",
    }
}

/// Map a policy `Decision` to the string surfaced by `query_policy`.
///
/// Unlike [`decision_to_str`] (which collapses the unspecified case to the
/// empty string for the audit-event surface), a policy verdict always names its
/// decision — an unspecified verdict becomes `"unspecified"`.
fn policy_decision_to_str(value: i32) -> &'static str {
    match Decision::try_from(value).unwrap_or(Decision::Unspecified) {
        Decision::Allow => "allow",
        Decision::Deny => "deny",
        Decision::Pending => "pending",
        Decision::Redact => "redact",
        Decision::Unspecified => "unspecified",
    }
}

#[pyfunction]
fn audit_event_to_wire_bytes(py: Python<'_>, event: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    let proto = audit_event_from_py(event)?;
    let encoded = proto.encode_to_vec();
    Ok(PyBytes::new(py, &encoded).into_any().unbind())
}

#[pyfunction]
fn audit_event_from_wire_bytes(py: Python<'_>, data: &Bound<'_, PyBytes>) -> PyResult<Py<PyAny>> {
    let proto = AuditEvent::decode(data.as_bytes()).map_err(|error| {
        PyValueError::new_err(format!("failed to decode AuditEvent wire bytes: {error}"))
    })?;
    audit_event_to_py(py, &proto)
}

#[pymodule]
fn _core(_py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<GovernanceEvent>()?;
    module.add_class::<RuntimeClient>()?;
    module.add_function(wrap_pyfunction!(audit_event_to_wire_bytes, module)?)?;
    module.add_function(wrap_pyfunction!(audit_event_from_wire_bytes, module)?)?;
    Ok(())
}
