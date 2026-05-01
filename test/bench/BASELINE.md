# Benchmark Baseline Results

Captured: 2026-05-01

## Environment

- Python: 3.12.4
- Platform: macOS arm64 (Apple M3 Max)
- pytest-benchmark: 4.0+

## Adapter Hook Overhead (register + unregister cycle)

Contract: < 2ms per call (AAASM-45)

| Adapter         | Min (us) | Mean (us) | P99 (us) | Status |
|-----------------|----------|-----------|----------|--------|
| LangChain       | 0.58     | 0.85      | ~3       | PASS   |
| LangGraph       | 0.67     | 0.92      | ~3       | PASS   |
| MCP             | 0.83     | 1.09      | ~4       | PASS   |
| Pydantic AI     | 1.29     | 1.66      | ~5       | PASS   |
| OpenAI Agents   | 1.50     | 2.00      | ~6       | PASS   |
| CrewAI          | 2.29     | 2.73      | ~8       | PASS   |

All adapters are well under the 2ms (2000us) contract threshold.

## Detection Overhead (AdapterRegistry.auto_detect)

Contract: < 50ms on first call (AAASM-47)

| Frameworks Installed | Min (ms) | Mean (ms) | Max (ms) | Status |
|----------------------|----------|-----------|----------|--------|
| 0                    | 1.08     | 1.26      | 4.75     | PASS   |
| 1                    | 1.07     | 1.32      | 9.27     | PASS   |
| 2                    | 1.08     | 1.29      | 9.63     | PASS   |
| 4                    | 1.08     | 1.25      | 5.64     | PASS   |

Detection scales linearly and remains well under the 50ms contract.

## init_assembly() Cold Start

| Metric   | Value (ms) |
|----------|------------|
| Min      | 1.31       |
| Mean     | 1.53       |
| Max      | 8.09       |

## PyO3 FFI Round-Trip

Skipped — native `_core` module not built in this environment.
Requires `maturin develop` with Rust toolchain.

## Notes

- All measurements use `--benchmark-disable-gc` for consistency
- Adapter benchmarks use mock framework classes to isolate wiring overhead
- Detection benchmarks include entry-point discovery overhead
- CI results may differ due to different hardware; use relative comparisons
