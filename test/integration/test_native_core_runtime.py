from __future__ import annotations

import gc
import os
import threading
import time
import tracemalloc

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


@pytest.mark.integration
def test_runtime_client_has_no_thread_deadlock(native_core) -> None:
    client = native_core.RuntimeClient.connect("/tmp/aaasm55.sock")
    errors: list[Exception] = []

    def worker(worker_id: int) -> None:
        try:
            for index in range(100):
                client.send_event(native_core.GovernanceEvent(f'{{"worker": {worker_id}, "idx": {index}}}'))
                client.query_policy({"action": "tool.call", "timeout_ms": 50})
        except Exception as error:  # pragma: no cover - runtime guard
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(worker_id,)) for worker_id in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    try:
        assert all(not thread.is_alive() for thread in threads)
        assert errors == []
    finally:
        client.close()


@pytest.mark.integration
def test_runtime_client_tracemalloc_leak_guard(native_core) -> None:
    client = native_core.RuntimeClient.connect("/tmp/aaasm55.sock")
    tracemalloc.start()
    baseline_current, _ = tracemalloc.get_traced_memory()
    try:
        for index in range(10_000):
            client.send_event(native_core.GovernanceEvent(f'{{"index": {index}}}'))
        gc.collect()
        current, _ = tracemalloc.get_traced_memory()
        assert current - baseline_current < 1_000_000
    finally:
        tracemalloc.stop()
        client.close()
