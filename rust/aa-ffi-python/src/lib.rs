//! aa-ffi-python crate bootstrap.

use once_cell::sync::Lazy;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use serde_json::Value;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;
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

#[pyclass(module = "agent_assembly._core")]
#[derive(Clone)]
struct GovernanceEvent {
    #[pyo3(get)]
    payload_json: String,
}

#[pymethods]
impl GovernanceEvent {
    #[new]
    fn new(payload_json: String) -> Self {
        Self { payload_json }
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
}

enum WorkerMessage {
    Event(GovernanceEvent),
    PolicyQuery {
        action_json: String,
        response_tx: oneshot::Sender<PolicyResultPayload>,
    },
    Close,
}

#[derive(Clone)]
struct PolicyResultPayload {
    allowed: bool,
    reason: String,
}

enum PolicyWaitError {
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
        }
    }

    #[staticmethod]
    fn connect(socket_path: String) -> Self {
        let _ = &*TOKIO_RUNTIME;
        let (sender, mut receiver) = mpsc::unbounded_channel::<WorkerMessage>();
        let closed = Arc::new(AtomicBool::new(false));
        let closed_for_task = Arc::clone(&closed);
        TOKIO_RUNTIME.spawn(async move {
            while let Some(message) = receiver.recv().await {
                match message {
                    WorkerMessage::Event(_event) => {}
                    WorkerMessage::PolicyQuery {
                        action_json,
                        response_tx,
                    } => {
                        let policy_result = evaluate_policy_action(&action_json);
                        let _ = response_tx.send(policy_result);
                    }
                    WorkerMessage::Close => break,
                }
            }
            closed_for_task.store(true, Ordering::SeqCst);
        });
        Self {
            socket_path,
            sender: Some(sender),
            closed,
        }
    }

    fn send_event(&self, event: GovernanceEvent) -> PyResult<()> {
        if self.closed.load(Ordering::SeqCst) {
            return Err(PyRuntimeError::new_err("runtime client is closed"));
        }
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
        let action_json = serialize_action_to_json(py, action)?;
        let timeout_ms = extract_timeout_ms(action);
        let sender = self
            .sender
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("runtime event queue is unavailable"))?;
        let (response_tx, response_rx) = oneshot::channel::<PolicyResultPayload>();
        sender
            .send(WorkerMessage::PolicyQuery {
                action_json,
                response_tx,
            })
            .map_err(|_| PyRuntimeError::new_err("failed to enqueue policy query"))?;
        let payload = py.allow_threads(|| wait_for_policy_response(timeout_ms, response_rx));
        let payload = payload.map_err(|error| match error {
            PolicyWaitError::Timeout => PolicyTimeoutError::new_err("policy query timed out"),
            PolicyWaitError::Disconnected => {
                PyRuntimeError::new_err("failed to resolve policy query")
            }
        })?;
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

fn evaluate_policy_action(action_json: &str) -> PolicyResultPayload {
    let parsed: Value = serde_json::from_str(action_json).unwrap_or(Value::Null);
    let deny_flag = parsed
        .as_object()
        .and_then(|obj| obj.get("deny"))
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if deny_flag {
        return PolicyResultPayload {
            allowed: false,
            reason: "Denied by local policy rule.".to_string(),
        };
    }
    PolicyResultPayload {
        allowed: true,
        reason: String::new(),
    }
}

fn wait_for_policy_response(
    timeout_ms: u64,
    response_rx: oneshot::Receiver<PolicyResultPayload>,
) -> Result<PolicyResultPayload, PolicyWaitError> {
    TOKIO_RUNTIME
        .block_on(async move { time::timeout(Duration::from_millis(timeout_ms), response_rx).await })
        .map_err(|_| PolicyWaitError::Timeout)?
        .map_err(|_| PolicyWaitError::Disconnected)
}

#[pymodule]
fn _core(py: Python<'_>, module: &PyModule) -> PyResult<()> {
    module.add("PolicyTimeoutError", py.get_type::<PolicyTimeoutError>())?;
    module.add_class::<GovernanceEvent>()?;
    module.add_class::<PolicyResult>()?;
    module.add_class::<RuntimeClient>()?;
    Ok(())
}
