//! aa-ffi-python crate bootstrap.

use pyo3::prelude::*;

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

#[pymodule]
fn _core(_py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<GovernanceEvent>()?;
    Ok(())
}
