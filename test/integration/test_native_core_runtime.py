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


@pytest.mark.integration
def test_query_policy_returns_quickly_and_times_out(native_core) -> None:
    client = native_core.RuntimeClient.connect("/tmp/aaasm55.sock")
    try:
        start = time.perf_counter()
        result = client.query_policy({"action": "tool.call", "timeout_ms": 50})
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        assert elapsed_ms < 50.0
        assert result.allowed is True

        with pytest.raises(native_core.PolicyTimeoutError):
            client.query_policy({"action": "slow.call", "delay_ms": 200, "timeout_ms": 10})
    finally:
        client.close()
