from __future__ import annotations

import os
import time

import pytest


@pytest.fixture()
def native_core():
    if os.getenv("AAASM_RUN_NATIVE_CORE_TESTS") != "1":
        pytest.skip("Set AAASM_RUN_NATIVE_CORE_TESTS=1 to run native core runtime tests.")
    return pytest.importorskip("agent_assembly._core")


@pytest.mark.integration
def test_send_event_is_non_blocking(native_core) -> None:
    client = native_core.RuntimeClient.connect("/tmp/aaasm55.sock")
    try:
        start = time.perf_counter()
        for index in range(500):
            client.send_event(native_core.GovernanceEvent(f'{{"index": {index}}}'))
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        assert elapsed_ms < 50.0
    finally:
        client.close()
