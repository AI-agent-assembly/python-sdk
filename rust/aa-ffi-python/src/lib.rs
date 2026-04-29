//! aa-ffi-python crate bootstrap.

use once_cell::sync::Lazy;
use pyo3::prelude::*;
use tokio::runtime::Runtime;

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
}

#[pymethods]
impl RuntimeClient {
    #[new]
    fn new(socket_path: String) -> Self {
        Self { socket_path }
    }
}

#[pymodule]
fn _core(_py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<GovernanceEvent>()?;
    module.add_class::<PolicyResult>()?;
    module.add_class::<RuntimeClient>()?;
    Ok(())
}
