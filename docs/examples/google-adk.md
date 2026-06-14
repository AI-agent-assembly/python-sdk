# Google ADK

Integrates Agent Assembly with [Google ADK](https://google.github.io/adk-docs/) (Agent Development Kit) to enforce governance policy on tool calls before they execute.

## What this example demonstrates

- Initializing Agent Assembly with `init_assembly()` in offline `sdk-only` mode.
- Installing Google ADK tool-level governance hooks — `GoogleADKAdapter` patches `google.adk.tools.BaseTool.run_async`.
- Running an **allowed** tool call (`get_weather`), a **denied** tool call (`delete_records`), and a **pending** tool call (`send_email`, which requires approval and is auto-denied offline).
- How `PolicyViolationError` is raised when a tool is blocked or rejected during approval.
- Replaying a **scripted tool trajectory** — no live Gemini / Vertex AI LLM and no cloud credentials are involved.

## The framework / library

[Google ADK](https://google.github.io/adk-docs/) (Agent Development Kit) is the agent framework governed in this example.

Version pins (from `pyproject.toml`):

| Dependency | Version |
|---|---|
| `google-adk` | `>=1.0.0,<2.0` |
| `agent-assembly` | `>=0.0.1a2` |
| Python | `>=3.12` |

## How it works

`init_assembly()` is opened as a context manager in offline `sdk-only` mode with the agent id `google-adk-demo-agent`:

```python
with init_assembly(
    gateway_url=gateway_url,
    api_key=api_key,
    agent_id="google-adk-demo-agent",
    mode="sdk-only",
) as ctx:
    ...
```

**Offline note.** Google ADK normally drives its agent loop against a cloud LLM (Gemini / Vertex AI), which requires credentials and a live network call. To stay runnable with no secrets, the example does not start a live model. Instead it replays a *scripted tool trajectory*: it builds real ADK `BaseTool` instances (`src/tools.py`) and invokes `run_async` directly — the exact surface the governance adapter patches. The genuine allow / deny / pending governance code runs; only the LLM that would *choose* the tools is mocked out.

**ADK 1.x adapter / version note.** In ADK 1.x, concrete tools (`FunctionTool` and custom `BaseTool` subclasses) override `run_async`, so patching the `BaseTool` base class alone does not intercept them. The example therefore applies the adapter's tool patch to the concrete demo tool class directly (see `src/governance.py`), the same mechanism the Agent Assembly SDK's own integration tests use. A future adapter release that patches concrete tool classes will let `init_assembly()`'s auto-detection wire this for you.

The concrete `DemoTool` class is governed *before* `init_assembly()` so the offline `LocalPolicyEngine` stays wired as the interceptor (the patch is idempotent):

```python
govern_tool_class(DemoTool, LocalPolicyEngine())
```

The adapter calls `check_tool_start` (and, for pending tools, `wait_for_tool_approval`) as `async` hooks on `LocalPolicyEngine` (`src/policy.py`). These return decision dicts in the gateway wire format `{"status": "allow" | "deny" | "pending"}`. `delete_records` and `write_file` are denied; `send_email` is pending and, with no approver available offline, is denied during approval.

## Prerequisites & running it

See [Preparing the runtime environment](preparing-the-runtime-environment.md) for the shared prerequisites.

Then run the example (offline — no Google Cloud credentials and no running gateway required):

```bash
cd python/google-adk
uv sync --extra dev
uv run python src/main.py
```

## Code walkthrough

Applying the adapter's tool patch to a concrete ADK tool class (`src/governance.py`):

```python
from agent_assembly.adapters.google_adk import patch as google_adk_patch


def govern_tool_class(tool_cls: type[Any], interceptor: Any) -> None:
    google_adk_patch._apply_tool_run_async_patch(tool_cls, interceptor)


def ungovern_tool_class(tool_cls: type[Any]) -> None:
    google_adk_patch._revert_tool_run_async_patch(tool_cls)
```

The offline policy engine returns gateway-format decisions (`src/policy.py`):

```python
async def check_tool_start(self, **kwargs: Any) -> dict[str, str]:
    tool_name = str(kwargs.get("tool_name", ""))
    if tool_name in DENIED_TOOLS:
        return {
            "status": "deny",
            "reason": (
                f"Tool '{tool_name}' is blocked by policy rule "
                "'deny_destructive_operations'."
            ),
        }
    if tool_name in PENDING_TOOLS:
        return {
            "status": "pending",
            "reason": f"Tool '{tool_name}' requires human approval before execution.",
        }
    return {"status": "allow"}
```

For a pending tool, offline approval resolves to a deny because no approver exists (`src/policy.py`):

```python
async def wait_for_tool_approval(self, **kwargs: Any) -> dict[str, str]:
    """Offline mode: no approver is available, so pending tools are denied."""
    tool_name = str(kwargs.get("tool_name", ""))
    return {
        "status": "deny",
        "reason": (
            f"Tool '{tool_name}' requires approval, but no approver is available "
            "in offline mode."
        ),
    }
```

## Notes & caveats

!!! note "Scripted trajectory (offline)"
    Google ADK drives its agent loop against a cloud LLM (Gemini / Vertex AI), which requires credentials and a network call. To keep the example runnable with no secrets, it does not start a live model — it replays a scripted tool trajectory that builds real ADK `BaseTool` instances and invokes `run_async` directly. The genuine allow / deny / pending governance code runs; only the LLM that would choose the tools is mocked out.

!!! warning "ADK 1.x concrete-tool patch"
    In ADK 1.x, concrete tools (`FunctionTool` and custom `BaseTool` subclasses) override `run_async`, so patching the `BaseTool` base class alone does not intercept them. This example applies the adapter's tool patch to the concrete demo tool class directly (see `src/governance.py`). With a future adapter release that patches concrete tool classes, `init_assembly()`'s auto-detection will wire this for you.

Troubleshooting (from the README):

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: agent_assembly` | Run `uv sync` first |
| `ModuleNotFoundError: google.adk` | Run `uv sync` — `google-adk` is a required dependency |
| `PolicyViolationError` in tests | Expected — the deny/pending policy rules are intentional |

## Expected behavior

```
==============================================================
  Agent Assembly — Google ADK Governed Agent Demo
==============================================================

Initializing Agent Assembly (gateway: http://localhost:8080, sdk-only mode)...
  Agent:    google-adk-demo-agent
  Gateway:  http://localhost:8080
  Mode:     sdk-only (offline demo)

Policy rules (local simulation of gateway policy):
  DENY    — delete_records, write_file  (destructive operations)
  PENDING — send_email                  (requires human approval)
  ALLOW   — everything else

Replaying scripted tool trajectory (no live LLM):
--------------------------------------------
  → get_weather(...)
     ✅ ALLOWED  — Weather: 22C, partly cloudy (mock response)

  → delete_records(...)
     ❌ BLOCKED  — Tool 'delete_records' blocked by governance policy: Tool 'delete_records' is blocked by policy rule 'deny_destructive_operations'.

  → send_email(...)
     ❌ BLOCKED  — Tool 'send_email' rejected during approval: Tool 'send_email' requires approval, but no approver is available in offline mode.

Assembly context shut down.
```

## Links

- [Example directory](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python/google-adk)
- [Example README](https://github.com/ai-agent-assembly/agent-assembly-examples/blob/master/python/google-adk/README.md)
- [Google ADK documentation](https://google.github.io/adk-docs/)
