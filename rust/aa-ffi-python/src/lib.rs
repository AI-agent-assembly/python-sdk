//! aa-ffi-python crate bootstrap.

use aa_core::AuditEntry;
use aa_proto::assembly::audit::v1::AuditEvent;
use aa_proto::assembly::audit::v1::CallStackNode as ProtoCallStackNode;
use aa_proto::assembly::common::v1::ActionType;
use aa_proto::assembly::common::v1::Decision;
use aa_proto::assembly::policy::v1::CheckActionRequest;
use aa_proto::assembly::policy::v1::CheckActionResponse;
use once_cell::sync::Lazy;
use prost::Message;
use pyo3::exceptions::PyValueError;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tokio::net::UnixStream;
use tokio::runtime::Runtime;
use tokio::sync::{mpsc, oneshot};
use tokio::time;

pyo3::create_exception!(_core, PolicyTimeoutError, pyo3::exceptions::PyTimeoutError);

static TOKIO_RUNTIME: Lazy<Runtime> = Lazy::new(|| {
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .thread_name("aa-ffi-python")
        .build()
        .expect("failed to build aa-ffi-python tokio runtime")
});

const TAG_POLICY_QUERY: u8 = 1;
const TAG_EVENT_REPORT: u8 = 2;
const TAG_HEARTBEAT: u8 = 4;

const TAG_POLICY_RESPONSE: u8 = 1;
const TAG_ACK: u8 = 3;

#[pyclass(module = "agent_assembly._core")]
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

#[pyclass(module = "agent_assembly._core")]
#[derive(Clone)]
struct PolicyResult {
    #[pyo3(get)]
    allowed: bool,
    #[pyo3(get)]
    reason: String,
}

#[pymethods]
impl PolicyResult {
    #[new]
    fn new(allowed: bool, reason: Option<String>) -> Self {
        Self {
            allowed,
            reason: reason.unwrap_or_default(),
        }
    }
}

#[pyclass(module = "agent_assembly._core")]
struct RuntimeClient {
    #[pyo3(get)]
    socket_path: String,
    sender: Option<mpsc::UnboundedSender<WorkerMessage>>,
    closed: Arc<AtomicBool>,
    last_error: Arc<Mutex<Option<String>>>,
}

enum WorkerMessage {
    Event(GovernanceEvent),
    PolicyQuery {
        action_json: String,
        timeout_ms: u64,
        response_tx: oneshot::Sender<Result<PolicyResultPayload, WorkerError>>,
    },
    Close,
}

#[derive(Clone)]
struct PolicyResultPayload {
    allowed: bool,
    reason: String,
}

#[derive(Debug)]
enum WorkerError {
    Timeout,
    Disconnected,
    Transport(String),
    Decode(String),
}

enum WorkerWaitError {
    Timeout,
    Disconnected,
}

#[pymethods]
impl RuntimeClient {
    #[new]
    fn new(socket_path: String) -> Self {
        Self {
            socket_path,
            sender: None,
            closed: Arc::new(AtomicBool::new(true)),
            last_error: Arc::new(Mutex::new(None)),
        }
    }

    #[staticmethod]
    fn connect(socket_path: String) -> Self {
        let _ = &*TOKIO_RUNTIME;

        let (sender, receiver) = mpsc::unbounded_channel::<WorkerMessage>();
        let closed = Arc::new(AtomicBool::new(false));
        let last_error = Arc::new(Mutex::new(None));

        TOKIO_RUNTIME.spawn(worker_loop(
            socket_path.clone(),
            receiver,
            Arc::clone(&closed),
            Arc::clone(&last_error),
        ));

        Self {
            socket_path,
            sender: Some(sender),
            closed,
            last_error,
        }
    }

    fn send_event(&self, event: GovernanceEvent) -> PyResult<()> {
        ensure_client_open(self.closed.as_ref(), self.last_error.as_ref())?;
        let sender = self
            .sender
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("runtime event queue is unavailable"))?;
        sender
            .send(WorkerMessage::Event(event))
            .map_err(|_| PyRuntimeError::new_err("failed to enqueue governance event"))?;
        Ok(())
    }

    fn query_policy(&self, py: Python<'_>, action: &PyAny) -> PyResult<PolicyResult> {
        ensure_client_open(self.closed.as_ref(), self.last_error.as_ref())?;
        let action_json = serialize_action_to_json(py, action)?;
        let timeout_ms = extract_timeout_ms(action);
        let sender = self
            .sender
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("runtime event queue is unavailable"))?;

        let (response_tx, response_rx) = oneshot::channel::<Result<PolicyResultPayload, WorkerError>>();
        sender
            .send(WorkerMessage::PolicyQuery {
                action_json,
                timeout_ms,
                response_tx,
            })
            .map_err(|_| PyRuntimeError::new_err("failed to enqueue policy query"))?;

        let worker_result = py.allow_threads(|| wait_for_worker_response(timeout_ms + 100, response_rx));
        let worker_result = worker_result.map_err(|error| match error {
            WorkerWaitError::Timeout => PolicyTimeoutError::new_err("policy query timed out"),
            WorkerWaitError::Disconnected => PyRuntimeError::new_err("policy worker disconnected"),
        })?;

        let payload = worker_result.map_err(map_worker_error_to_py)?;
        Ok(PolicyResult {
            allowed: payload.allowed,
            reason: payload.reason,
        })
    }

    fn close(&mut self) {
        if self.closed.swap(true, Ordering::SeqCst) {
            return;
        }
        if let Some(sender) = self.sender.take() {
            let _ = sender.send(WorkerMessage::Close);
        }
    }
}

async fn worker_loop(
    socket_path: String,
    mut receiver: mpsc::UnboundedReceiver<WorkerMessage>,
    closed: Arc<AtomicBool>,
    last_error: Arc<Mutex<Option<String>>>,
) {
    let stream = match UnixStream::connect(&socket_path).await {
        Ok(stream) => stream,
        Err(error) => {
            set_worker_error(last_error.as_ref(), format!("failed to connect runtime socket: {error}"));
            closed.store(true, Ordering::SeqCst);
            return;
        }
    };

    let (mut reader, mut writer) = stream.into_split();
    if let Err(error) = write_heartbeat(&mut writer).await {
        set_worker_error(last_error.as_ref(), format!("failed to send heartbeat: {error:?}"));
        closed.store(true, Ordering::SeqCst);
        return;
    }

    match read_runtime_response(&mut reader).await {
        Ok(RuntimeResponse::Ack) => {}
        Ok(_) => {
            set_worker_error(last_error.as_ref(), "unexpected heartbeat response from runtime".to_string());
            closed.store(true, Ordering::SeqCst);
            return;
        }
        Err(error) => {
            set_worker_error(last_error.as_ref(), format!("failed to read heartbeat ack: {error}"));
            closed.store(true, Ordering::SeqCst);
            return;
        }
    }

    while let Some(message) = receiver.recv().await {
        match message {
            WorkerMessage::Event(event) => {
                let send_result = send_event_frame(&mut writer, &event).await;
                if let Err(error) = send_result {
                    set_worker_error(last_error.as_ref(), format!("failed to send event: {error:?}"));
                    break;
                }

                match read_runtime_response(&mut reader).await {
                    Ok(RuntimeResponse::Ack) => {}
                    Ok(_) => {
                        set_worker_error(last_error.as_ref(), "unexpected event ack response from runtime".to_string());
                        break;
                    }
                    Err(error) => {
                        set_worker_error(last_error.as_ref(), format!("failed to read event ack: {error}"));
                        break;
                    }
                }
            }
            WorkerMessage::PolicyQuery {
                action_json,
                timeout_ms,
                response_tx,
            } => {
                let response = process_policy_query(&mut reader, &mut writer, action_json, timeout_ms).await;
                let _ = response_tx.send(response);
            }
            WorkerMessage::Close => break,
        }
    }

    closed.store(true, Ordering::SeqCst);
}

async fn send_event_frame<W>(writer: &mut W, event: &GovernanceEvent) -> Result<(), WorkerError>
where
    W: AsyncWrite + Unpin,
{
    let entry = &event.audit_entry;
    let event_type = format!("{:?}", entry.event_type());
    let agent_id_hex = bytes_to_hex(entry.agent_id().as_bytes());
    let session_id_hex = bytes_to_hex(entry.session_id().as_bytes());
    let audit_event = AuditEvent {
        event_id: make_event_id(),
        trace_id: "python-sdk".to_string(),
        span_id: "ffi-send-event".to_string(),
        decision: Decision::Allow as i32,
        labels: std::collections::HashMap::from([
            (String::from("payload_json"), event.payload_json.clone()),
            (String::from("event_type"), event_type),
            (String::from("agent_id_hex"), agent_id_hex),
            (String::from("session_id_hex"), session_id_hex),
            (String::from("payload"), entry.payload().to_string()),
        ]),
        ..Default::default()
    };
    let payload = audit_event.encode_to_vec();
    write_frame(writer, TAG_EVENT_REPORT, &payload).await
}

async fn process_policy_query<R, W>(
    reader: &mut R,
    writer: &mut W,
    action_json: String,
    timeout_ms: u64,
) -> Result<PolicyResultPayload, WorkerError>
where
    R: AsyncRead + Unpin,
    W: AsyncWrite + Unpin,
{
    let request = CheckActionRequest {
        trace_id: action_json,
        span_id: "ffi-query-policy".to_string(),
        ..Default::default()
    };
    let payload = request.encode_to_vec();
    write_frame(writer, TAG_POLICY_QUERY, &payload).await?;

    let response = time::timeout(
        Duration::from_millis(timeout_ms),
        read_runtime_response(reader),
    )
    .await
    .map_err(|_| WorkerError::Timeout)?
    .map_err(|error| WorkerError::Transport(error))?;

    match response {
        RuntimeResponse::PolicyResponse(bytes) => {
            let policy = CheckActionResponse::decode(bytes.as_slice())
                .map_err(|error| WorkerError::Decode(error.to_string()))?;
            let allowed = matches!(policy.decision, x if x == Decision::Allow as i32 || x == Decision::Redact as i32);
            Ok(PolicyResultPayload {
                allowed,
                reason: policy.reason,
            })
        }
        RuntimeResponse::Ack => Err(WorkerError::Transport(
            "runtime returned ACK instead of policy response".to_string(),
        )),
        RuntimeResponse::Unknown(tag, _) => Err(WorkerError::Transport(format!(
            "runtime returned unexpected tag {tag} for policy query"
        ))),
    }
}

fn map_worker_error_to_py(error: WorkerError) -> PyErr {
    match error {
        WorkerError::Timeout => PolicyTimeoutError::new_err("policy query timed out"),
        WorkerError::Disconnected => PyRuntimeError::new_err("policy worker disconnected"),
        WorkerError::Transport(message) | WorkerError::Decode(message) => PyRuntimeError::new_err(message),
    }
}

fn ensure_client_open(closed: &AtomicBool, last_error: &Mutex<Option<String>>) -> PyResult<()> {
    if !closed.load(Ordering::SeqCst) {
        return Ok(());
    }

    if let Ok(guard) = last_error.lock() {
        if let Some(message) = guard.as_ref() {
            return Err(PyRuntimeError::new_err(message.clone()));
        }
    }

    Err(PyRuntimeError::new_err("runtime client is closed"))
}

fn extract_timeout_ms(action: &PyAny) -> u64 {
    action
        .downcast::<PyDict>()
        .ok()
        .and_then(|dict| dict.get_item("timeout_ms").ok().flatten())
        .and_then(|value| value.extract::<u64>().ok())
        .unwrap_or(50)
}

fn serialize_action_to_json(py: Python<'_>, action: &PyAny) -> PyResult<String> {
    let json_module = PyModule::import(py, "json")?;
    let dumped = json_module.call_method1("dumps", (action,))?;
    dumped.extract::<String>()
}

fn set_worker_error(last_error: &Mutex<Option<String>>, message: String) {
    if let Ok(mut guard) = last_error.lock() {
        *guard = Some(message);
    }
}

fn make_event_id() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};

    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    format!("py-{}-{}", now.as_secs(), now.subsec_nanos())
}

fn action_type_from_str(value: &str) -> i32 {
    match value {
        "llm_call" => ActionType::LlmCall as i32,
        "tool_call" => ActionType::ToolCall as i32,
        "file_op" | "file_operation" => ActionType::FileOperation as i32,
        "network_call" => ActionType::NetworkCall as i32,
        "process_exec" => ActionType::ProcessExec as i32,
        "agent_spawn" => ActionType::AgentSpawn as i32,
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

fn call_stack_node_from_py(node: &PyAny) -> PyResult<ProtoCallStackNode> {
    let id = node.getattr("id")?.extract::<String>()?;
    let kind = node.getattr("kind")?.extract::<String>()?;
    let label = node.getattr("label")?.extract::<String>()?;
    let latency_ms = node
        .getattr("latency_ms")?
        .extract::<Option<i64>>()?
        .unwrap_or(0);
    let children_py = node.getattr("children")?;
    let mut children = Vec::new();
    for child in children_py.iter()? {
        children.push(call_stack_node_from_py(child?)?);
    }
    Ok(ProtoCallStackNode {
        id,
        kind,
        label,
        latency_ms,
        children,
    })
}

fn call_stack_node_to_py(py: Python<'_>, node: &ProtoCallStackNode) -> PyResult<PyObject> {
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
    let children = pyo3::types::PyList::empty(py);
    for child in &node.children {
        children.append(call_stack_node_to_py(py, child)?)?;
    }
    kwargs.set_item("children", children)?;
    Ok(cls.call((), Some(kwargs))?.into())
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

fn bytes_to_hex(bytes: &[u8; 16]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut result = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        result.push(HEX[(byte >> 4) as usize] as char);
        result.push(HEX[(byte & 0x0F) as usize] as char);
    }
    result
}

enum RuntimeResponse {
    Ack,
    PolicyResponse(Vec<u8>),
    Unknown(u8, Vec<u8>),
}

async fn write_heartbeat<W>(writer: &mut W) -> Result<(), WorkerError>
where
    W: AsyncWrite + Unpin,
{
    writer
        .write_u8(TAG_HEARTBEAT)
        .await
        .map_err(|error| WorkerError::Transport(error.to_string()))?;
    writer
        .flush()
        .await
        .map_err(|error| WorkerError::Transport(error.to_string()))
}

async fn write_frame<W>(writer: &mut W, tag: u8, payload: &[u8]) -> Result<(), WorkerError>
where
    W: AsyncWrite + Unpin,
{
    writer
        .write_u8(tag)
        .await
        .map_err(|error| WorkerError::Transport(error.to_string()))?;
    write_varint(writer, payload.len() as u64).await?;
    writer
        .write_all(payload)
        .await
        .map_err(|error| WorkerError::Transport(error.to_string()))?;
    writer
        .flush()
        .await
        .map_err(|error| WorkerError::Transport(error.to_string()))
}

async fn read_runtime_response<R>(reader: &mut R) -> Result<RuntimeResponse, String>
where
    R: AsyncRead + Unpin,
{
    let tag = reader.read_u8().await.map_err(|error| error.to_string())?;
    match tag {
        TAG_ACK => {
            let _ = read_length_delimited(reader).await?;
            Ok(RuntimeResponse::Ack)
        }
        TAG_POLICY_RESPONSE => {
            let payload = read_length_delimited(reader).await?;
            Ok(RuntimeResponse::PolicyResponse(payload))
        }
        other => {
            let payload = read_length_delimited(reader).await?;
            Ok(RuntimeResponse::Unknown(other, payload))
        }
    }
}

async fn read_length_delimited<R>(reader: &mut R) -> Result<Vec<u8>, String>
where
    R: AsyncRead + Unpin,
{
    let len = read_varint(reader).await? as usize;
    let mut payload = vec![0u8; len];
    reader
        .read_exact(&mut payload)
        .await
        .map_err(|error| error.to_string())?;
    Ok(payload)
}

async fn read_varint<R>(reader: &mut R) -> Result<u64, String>
where
    R: AsyncRead + Unpin,
{
    let mut result: u64 = 0;
    let mut shift = 0u32;
    loop {
        let byte = reader.read_u8().await.map_err(|error| error.to_string())?;
        result |= ((byte & 0x7F) as u64) << shift;
        if byte & 0x80 == 0 {
            break;
        }
        shift += 7;
        if shift >= 64 {
            return Err("varint too long".to_string());
        }
    }
    Ok(result)
}

async fn write_varint<W>(writer: &mut W, mut value: u64) -> Result<(), WorkerError>
where
    W: AsyncWrite + Unpin,
{
    loop {
        let byte = (value & 0x7F) as u8;
        value >>= 7;
        if value == 0 {
            writer
                .write_u8(byte)
                .await
                .map_err(|error| WorkerError::Transport(error.to_string()))?;
            break;
        }

        writer
            .write_u8(byte | 0x80)
            .await
            .map_err(|error| WorkerError::Transport(error.to_string()))?;
    }

    Ok(())
}

fn wait_for_worker_response(
    timeout_ms: u64,
    response_rx: oneshot::Receiver<Result<PolicyResultPayload, WorkerError>>,
) -> Result<Result<PolicyResultPayload, WorkerError>, WorkerWaitError> {
    TOKIO_RUNTIME
        .block_on(async move { time::timeout(Duration::from_millis(timeout_ms), response_rx).await })
        .map_err(|_| WorkerWaitError::Timeout)?
        .map_err(|_| WorkerWaitError::Disconnected)
}

#[pymodule]
fn _core(py: Python<'_>, module: &PyModule) -> PyResult<()> {
    module.add("PolicyTimeoutError", py.get_type::<PolicyTimeoutError>())?;
    module.add_class::<GovernanceEvent>()?;
    module.add_class::<PolicyResult>()?;
    module.add_class::<RuntimeClient>()?;
    Ok(())
}
