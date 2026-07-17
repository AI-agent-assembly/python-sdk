# Microsoft Agent Framework

Integrates Agent Assembly with [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) to enforce governance policy on tool calls before they execute.

## What this example demonstrates

- Initializing Agent Assembly with `init_assembly()` in offline `sdk-only` mode.
- Installing Microsoft Agent Framework tool-level governance hooks — `MicrosoftAgentFrameworkAdapter` patches `agent_framework.FunctionTool.invoke`, the single async coroutine through which **every** function tool executes.
- Running an **allowed** tool call (`get_weather`), a **denied** tool call (`delete_records`), and a **pending** tool call (`send_email`, which requires approval and is auto-denied offline).
- How `PolicyViolationError` is raised when a tool is blocked or rejected during approval.
- Two run paths from one example: an **offline mock path** that replays the governed tool calls through the policy contract with no `agent_framework` install, and a **live path** that drives the real `FunctionTool.invoke` through the installed adapter.

## The framework / library

[Microsoft Agent Framework](https://github.com/microsoft/agent-framework) is Microsoft's unified agent framework, governed in this example.

Version pins (from `pyproject.toml`):

| Dependency | Version |
|---|---|
| `agent-framework` (the `live` extra) | `>=1.9,<2` |
| `agent-assembly` | `>=0.0.1rc6` (the release that ships the Microsoft Agent Framework adapter) |
| Python | `>=3.12` |

The adapter's `get_supported_versions()` reports `>=1.0.0,<2.0` — governance attaches across the 1.x line.

**Install caveats — read these before installing the live extra:**

- The PyPI distribution is named **`agent-framework`** but it **imports as the top-level module `agent_framework`**. The adapter detects the importable module, not the distribution name.
- `agent-framework` pulls **pre-release** sub-distributions, so `uv` refuses to resolve the `live` extra by default. This example sets `prerelease = "allow"` under `[tool.uv]`, so `uv sync --extra live` resolves without a per-command flag. (Outside that config you would add `--prerelease=allow`; `pip` resolves them without a flag.)
- Some of those sub-distributions are **platform-specific** — for example `github-copilot-sdk` ships **macOS-only wheels** and has no Linux wheel. The **live** run is therefore best on macOS (or any platform where the wheels exist). On Linux CI the `live` extra cannot install, which is exactly why the offline path exists.

## How it works

`init_assembly()` is opened as a context manager in offline `sdk-only` mode with the agent id `microsoft-agent-framework-demo-agent`:

```python
with init_assembly(
    gateway_url=gateway_url,
    api_key=api_key,
    agent_id="microsoft-agent-framework-demo-agent",
    mode="sdk-only",
) as ctx:
    ...
```

**The hook point.** `MicrosoftAgentFrameworkAdapter` patches `agent_framework.FunctionTool.invoke` — the single async coroutine through which every function tool runs. Both the `@agent_framework.tool` decorator and direct `FunctionTool(...)` construction produce `FunctionTool` instances, and agents/workflows dispatch tool calls through `invoke`. Patching that one method governs all tool execution without requiring the user to register any framework middleware (which would be opt-in and bypassable).

**Detection.** The framework name (`microsoft_agent_framework`) deliberately differs from the importable module (`agent_framework`), so the adapter overrides `is_available()` to probe the real module rather than the framework name.

**Offline note.** Microsoft Agent Framework normally drives its agent loop against a chat model, which needs credentials and a live network call. To stay runnable with no secrets, the example does not start a live model. The mock path replays the three governed tool calls through the `LocalPolicyEngine` decision contract **without importing `agent_framework`**. The live path builds real `agent_framework.FunctionTool` instances (`src/tools.py`) and calls `tool.invoke(...)` directly — the exact surface the adapter patches — so the genuine governance code runs and only the model that would *choose* the tools is absent.

In the live path, the adapter is registered *before* `init_assembly()`. Because the patch is idempotent, registering first makes `init_assembly()`'s auto-detection a no-op and keeps the offline `LocalPolicyEngine` wired as the interceptor. The adapter calls `check_tool_start` (and, for pending tools, `wait_for_tool_approval`) as `async` hooks on `LocalPolicyEngine` (`src/policy.py`). These return decision dicts in the gateway wire format `{"status": "allow" | "deny" | "pending"}`. `delete_records` and `write_file` are denied; `send_email` is pending and, with no approver available offline, is denied during approval. A `deny` verdict raises `PolicyViolationError` *before* the wrapped function body runs, so a denied tool never executes its side effects.

## Prerequisites & running it

See [Preparing the runtime environment](preparing-the-runtime-environment.md) for the shared prerequisites.

### Offline / mock path (no `agent-framework` needed — what CI runs)

```bash
cd python/microsoft-agent-framework-tool-policy
uv sync --extra dev
uv run python src/main.py --mock
```

### Live path (drives the real framework)

The live path needs the `live` extra. Pre-releases are already allowed via `[tool.uv]`, so no extra flag is required (and it installs best on macOS, where the platform-specific wheels exist):

```bash
cd python/microsoft-agent-framework-tool-policy
uv sync --extra live --extra dev
uv run python src/main.py
```

The live run prints the same allow/deny/pending outcomes as the mock run, but each line is the result of the real `FunctionTool.invoke` passing through the patched governance hook — a denied tool raises `PolicyViolationError` before its body runs.

### Expected behavior

Running `uv run python src/main.py --mock` produces:

```
==============================================================
  Agent Assembly — Microsoft Agent Framework Governed Agent Demo
==============================================================

Initializing Agent Assembly (gateway: http://localhost:8080, sdk-only mode, mock)...
  Agent:    microsoft-agent-framework-demo-agent
  Gateway:  http://localhost:8080
  Mode:     sdk-only (offline demo)

Policy rules (local simulation of gateway policy):
  DENY    — delete_records, write_file  (destructive operations)
  PENDING — send_email                  (requires human approval)
  ALLOW   — everything else

Running governed tool calls (mock — policy contract, offline):
--------------------------------------------
  → invoke tool get_weather
     ✅ ALLOWED  — get_weather would execute

  → invoke tool delete_records
     ❌ BLOCKED  — Tool 'delete_records' is blocked by policy rule 'deny_destructive_operations'.

  → invoke tool send_email
     ❌ BLOCKED  — Tool 'send_email' requires approval, but no approver is available in offline mode.

Assembly context shut down.
```

| Tool | Governance control | Outcome |
|---|---|---|
| `get_weather` | allow rule | **ALLOWED** — body runs |
| `delete_records` | deny (destructive) | **BLOCKED** before body runs |
| `send_email` | pending → no approver offline | **BLOCKED** during approval |

### Smoke tests

```bash
# The governance smoke tests import the real framework; install the live extra:
uv sync --extra live --extra dev
uv run pytest tests/ -v
```

The smoke tests `pytest.importorskip("agent_framework")`, so they **skip cleanly** (rather than fail) when only the `dev` extra is installed. A `tests/conftest.py` additionally coerces pytest's "no tests collected" exit code to success, so a fully-skipped suite is reported green in CI rather than as a failure. When `agent_framework` *is* installed, the tests run and assert that a denied tool's `FunctionTool.invoke` raises `PolicyViolationError` before its body runs, while an allowed tool's body executes (a negative control against a no-op).

## Links

- [Example directory](https://github.com/ai-agent-assembly/examples/tree/master/python/microsoft-agent-framework-tool-policy)
- [Example README](https://github.com/ai-agent-assembly/examples/blob/master/python/microsoft-agent-framework-tool-policy/README.md)
- [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
