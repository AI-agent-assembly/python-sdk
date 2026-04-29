//! aa-ffi-python crate bootstrap.

use once_cell::sync::Lazy;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use serde_json::Value;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use tokio::runtime::Runtime;
use tokio::sync::{mpsc, oneshot};

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

#[derive(Clone)]
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

    fn query_policy(&self, py: Python<'_>, action: &Bound<'_, PyAny>) -> PyResult<PolicyResult> {
        let action_json = serialize_action_to_json(py, action)?;
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
        let payload = response_rx
            .blocking_recv()
            .map_err(|_| PyRuntimeError::new_err("failed to resolve policy query"))?;
        Ok(PolicyResult {
            allowed: payload.allowed,
            reason: payload.reason,
        })
    }
}

fn serialize_action_to_json(py: Python<'_>, action: &Bound<'_, PyAny>) -> PyResult<String> {
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

#[pymodule]
fn _core(_py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<GovernanceEvent>()?;
    module.add_class::<PolicyResult>()?;
    module.add_class::<RuntimeClient>()?;
    Ok(())
}
