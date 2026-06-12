# Configuration

Everything the SDK needs is passed to a single entry point, `init_assembly()`. This page
documents its parameters, how the gateway URL and API key are resolved when you omit them,
and the runtime / enforcement modes.

## `init_assembly()` parameters

```python
from agent_assembly import init_assembly

context = init_assembly(
    gateway_url="http://localhost:7391",
    api_key="dev-key",
    agent_id="my-agent-001",
    mode="auto",
)
```

| Parameter | Type | Default | Purpose |
| --- | --- | --- | --- |
| `gateway_url` | `str \| None` | resolver chain | Base URL of the governance gateway. See [resolution](#resolution-order) below. |
| `api_key` | `str \| None` | resolver chain | API key sent to the gateway. Resolved the same way as `gateway_url`. |
| `agent_id` | `str \| None` | `"agent-assembly-default"` | Stable identity for this agent in the registry/audit trail. |
| `mode` | `"auto" \| "ebpf" \| "proxy" \| "sdk-only"` | `"auto"` | Interception layer to activate. See [Runtime modes](#runtime-modes). |
| `enforcement_mode` | `"enforce" \| "observe" \| "disabled" \| None` | `None` | Governance posture sent at registration. See [Enforcement modes](#enforcement-modes). |
| `parent_agent_id` | `str \| None` | ambient/`None` | Lineage — the agent that spawned this one. Auto-filled from the spawn context when omitted. |
| `team_id` | `str \| None` | `None` | Team the agent belongs to (budget/policy scoping). |
| `delegation_reason` | `str \| None` | `None` | Why this sub-agent was spawned (≤ 256 chars). |
| `spawned_by_tool` | `str \| None` | ambient/`None` | Tool that spawned this agent. Auto-filled from the spawn context. |
| `depth` | `int \| None` | ambient/`None` | Delegation depth. Auto-filled from the spawn context. |

`init_assembly()` is **idempotent per process** — a second call with a compatible
configuration returns the already-active context instead of installing hooks twice.
The returned `AssemblyContext` is also a context manager, so prefer:

```python
with init_assembly(gateway_url="http://localhost:7391", api_key="dev-key", mode="sdk-only"):
    ...  # your agent runs here; hooks are torn down on exit
```

## Resolution order

When `gateway_url` / `api_key` are not passed explicitly, the SDK resolves each through a
fallback chain (see `agent_assembly.core.gateway_resolver`):

1. **Explicit argument** — the value you pass to `init_assembly()`.
2. **Environment variable** — `AAASM_GATEWAY_URL` / `AAASM_API_KEY`.
3. **Config file** — `~/.aasm/config.yaml`.
4. **Local default** — probe `http://localhost:7391/healthz`; if no gateway is running, the
   SDK attempts to **auto-start** a local one (`aasm start --mode local --foreground`).
   Auto-start needs the `aasm` binary on `PATH` — install it via the
   `agent-assembly[runtime]` extra or the Homebrew tap. Without it the SDK raises
   `ConfigurationError`.

This means a local development loop often needs no arguments at all — start a gateway with
`aasm`, or let the SDK start one for you.

For the full gateway configuration surface (policy files, budgets, mTLS) and the complete
`aasm` CLI reference, see the core
[Gateway configuration](https://ai-agent-assembly.github.io/agent-assembly/configuration/) and
[CLI reference](https://ai-agent-assembly.github.io/agent-assembly/cli/) docs.

```bash
export AAASM_GATEWAY_URL="https://gateway.example.com"
export AAASM_API_KEY="…"
```

### Config file format

The optional `~/.aasm/config.yaml` reads both values from an `agent:` section:

```yaml
agent:
  gateway_url: "https://gateway.example.com"
  api_key: "…"
```

Both values are read from the `agent.gateway_url` / `agent.api_key` keys. The file is advisory
— it is skipped silently when missing, when PyYAML is not installed, or when a key is absent,
so an explicit argument or environment variable always wins. The API key resolves through the
**same** four-step chain; if nothing supplies one, it defaults to an empty string, which the
gateway accepts in local mode.

## Runtime modes

`mode` selects which interception layer enforces policy. Passing an unknown value raises
`ConfigurationError`.

| Mode | Behaviour |
| --- | --- |
| `auto` (default) | Pick the best available layer for the current platform. |
| `sdk-only` | In-process only — framework adapters enforce on tool calls; no network sidecar. The most portable mode and the best choice for deterministic tests. |
| `proxy` | Route outbound traffic through the `aasm` sidecar proxy (network-egress policy without code changes). |
| `ebpf` | Kernel-level interception via eBPF. **Linux only** — raises `ConfigurationError` on unsupported platforms. |

## Enforcement modes

`enforcement_mode` is the governance posture the gateway applies to this agent. Leaving it
`None` omits the field so the gateway uses its server-side default (live `enforce`).

| Value | Behaviour |
| --- | --- |
| `enforce` | Default. A `deny` decision blocks the action; `redact` strips secrets. |
| `observe` | Dry-run — every action proceeds, but the gateway records would-be violations as shadow audit events. Good for rolling out policy safely. |
| `disabled` | Policy evaluation skipped entirely. Intended for hermetic tests only. |

For the conceptual difference between `mode` (*where* policy is enforced) and `enforcement_mode`
(*how hard* a deny bites), see [Core Concepts → Modes and enforcement](concepts/index.md#modes-and-enforcement).

## Next steps

- [Framework examples](guides/framework-examples.md) — wire the SDK into LangChain, CrewAI, and more.
- [Handling allow/deny decisions](guides/handling-decisions.md) — catch and respond to policy denials.
- [Troubleshooting](troubleshooting.md) — what each configuration error means.
