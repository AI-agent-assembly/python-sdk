# Troubleshooting

Common errors when integrating the SDK, what they mean, and how to fix them. Every exception
the SDK raises inherits from `agent_assembly.AssemblyError`, so you can catch that base type
as a backstop.

## Configuration errors

These are raised by `init_assembly()` **before** any side effect runs, so your retry logic is
safe.

| Message | Cause | Fix |
| --- | --- | --- |
| `gateway_url is required` | No gateway URL could be resolved (no argument, no `AAASM_GATEWAY_URL`, no config file, no local gateway). | Pass `gateway_url=...`, set `AAASM_GATEWAY_URL`, or start a local gateway. See [Configuration](configuration.md#resolution-order). |
| `mode must be one of: auto, ebpf, proxy, sdk-only` | An unknown `mode` value. | Use one of the four valid modes. |
| `enforcement_mode must be one of: enforce, observe, disabled` | An unknown `enforcement_mode`. | Use a valid posture or leave it `None`. |
| `eBPF mode is not supported on this platform.` | `mode="ebpf"` on a non-Linux host. | Use `mode="sdk-only"` or `mode="proxy"` off Linux. |
| `Failed to initialize assembly runtime: ...` | Adapter hook installation or the network layer failed during startup. | Read the wrapped cause; the SDK already rolled back any partial setup. |

## Can't reach the gateway

A `GatewayError` (or a connection error surfaced through it) means the SDK reached the
network layer but the gateway didn't answer.

- Confirm the gateway is running and the URL is correct — by default the SDK probes
  `http://localhost:7391/healthz`.
- Check `AAASM_GATEWAY_URL` / `AAASM_API_KEY` aren't pointing somewhere stale.
- For a quick local loop, run an `aasm` gateway yourself, or let the SDK auto-start one
  (`aasm start --mode local --foreground`). If auto-start fails, ensure the `aasm` binary is
  on `PATH` — install it via the `agent-assembly[runtime]` extra or the Homebrew tap.

## Tool calls are being blocked

`ToolExecutionBlockedError` (and its subtypes `PolicyViolationError`, `MCPToolBlockedError`)
are **not** SDK bugs — they mean the policy engine denied a tool call. This is the product
working as intended.

- To see *what* would be blocked without actually blocking, register the agent with
  `enforcement_mode="observe"` (dry-run) and inspect the shadow audit events.
- To allow the call, update the policy on the gateway side.
- For how to catch these in code (and which subtype to catch), see
  [Handling allow/deny decisions](guides/handling-decisions.md).

## The native extension isn't loading

The native PyO3 fast path is **optional**. If `agent_assembly._core` is unavailable you'll see
`RuntimeClient` / `GovernanceEvent` simply absent from `agent_assembly.__all__`, and
`AuditEvent.to_wire_bytes()` / `from_wire_bytes()` raise `ImportError`. The pure-Python SDK
still works.

To enable it:

```bash
pip install --pre 'agent-assembly[runtime]'   # bundled platform wheel, or
uv tool run maturin develop --manifest-path native/aa-ffi-python/Cargo.toml --release  # build locally (needs Rust)
```

## Still stuck?

Open a [GitHub issue](https://github.com/ai-agent-assembly/python-sdk/issues) with the full
traceback and your `init_assembly()` call (redact secrets).
