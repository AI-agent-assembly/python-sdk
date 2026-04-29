//! aa-ffi-python crate bootstrap.

use pyo3::prelude::*;

#[pymodule]
fn _core(_py: Python<'_>, _module: &Bound<'_, PyModule>) -> PyResult<()> {
    Ok(())
}
