# Pydantic AI

Integrate Agent Assembly with [Pydantic AI](https://ai.pydantic.dev/) to enforce governance policy on tool calls before they execute — driven fully offline.

## What this example demonstrates

- Initializing Agent Assembly with `init_assembly()` in offline `sdk-only` mode.
- Installing tool-level governance hooks with `PydanticAIAdapter`, which patches `pydantic_ai.tools.Tool._run`.
- Driving a real Pydantic AI `Agent` with the built-in `TestModel`, so the demo runs **offline with no API key**.
- Running an **allowed** tool call (`get_weather`), a **denied** tool call (`delete_records`), and a **pending** tool call (`send_email` — requires approval, auto-denied offline).
- How `PolicyViolationError` is raised when a tool is blocked or rejected during approval.

## The framework / library

This example builds on [Pydantic AI](https://ai.pydantic.dev/), the agent framework from the Pydantic team.

The Agent Assembly Pydantic AI adapter auto-detects the framework's tool-execution hook across versions (`Tool._run` on `<0.3.0`, `AbstractToolset.call_tool` on `>=0.3.0`). This example targets the tested `>=0.3.0` line, so `pyproject.toml` pins:

```toml
dependencies = [
    "agent-assembly>=0.0.1a2",
    # The Agent Assembly Pydantic AI adapter auto-detects the tool-execution
    # hook across versions: `Tool._run` on <0.3.0, and `AbstractToolset.call_tool`
    # on >=0.3.0 (where that internal entry point was renamed). `>=0.3.0` is the
    # tested line — the SDK's own dev/test group pins it, so it is the version
    # exercised in CI.
    "pydantic-ai>=0.3.0",
]
```

The adapter installs governance hooks on both the legacy (`<0.3.0`) and current (`>=0.3.0`) Pydantic AI lines; `>=0.3.0` is the continuously-tested line and the one this example targets. The example requires Python `>= 3.12` and the Agent Assembly Python SDK `>= 0.0.1a2`. For the full version-range table, see [Framework compatibility](../compatibility/frameworks.md).

## How it works

`init_assembly()` runs in `sdk-only` mode and, in production, auto-detects Pydantic AI and registers the adapter automatically. The `PydanticAIAdapter` patches `pydantic_ai.tools.Tool._run`, so every tool invocation is routed through a governance check before the tool body runs.

In `src/main.py`, the adapter is registered *before* `init_assembly()`. Because the patch is idempotent, registering first makes `init_assembly`'s auto-detection a no-op and keeps the offline `LocalPolicyEngine` wired as the governance interceptor:

```python
adapter = PydanticAIAdapter()
adapter.set_process_agent_id("pydantic-ai-demo-agent")
adapter.register_hooks(LocalPolicyEngine())

with init_assembly(
    gateway_url=gateway_url,
    api_key=api_key,
    agent_id="pydantic-ai-demo-agent",
    mode="sdk-only",
) as ctx:
    ...
```

In `src/agent.py`, the agent is built with `TestModel`, told which tool to call, so it deterministically exercises the allow / deny / pending paths offline. In `src/policy.py`, `LocalPolicyEngine.check_tool_start` returns a decision dict in the gateway wire format (`{"status": "allow" | "deny" | "pending"}`). A `deny`, or an unapproved `pending` resolved by `wait_for_tool_approval`, raises `PolicyViolationError` before the tool runs.

The policy rules are:

- **DENY** — `delete_records`, `write_file` (destructive operations)
- **PENDING** — `send_email` (requires human approval; auto-denied offline since no approver is available)
- **ALLOW** — everything else

## Prerequisites & running it

See [Preparing the runtime environment](preparing-the-runtime-environment.md) for the shared prerequisites.

This demo runs fully offline — no running Agent Assembly gateway and no LLM API key are required.

```bash
cd python/pydantic-ai
uv sync --extra dev
uv run python src/main.py
```

## Code walkthrough

The agent is wired with `TestModel` and told which tool to call, so each run deterministically triggers one tool (`src/agent.py`):

```python
def build_agent(call_tool: str) -> Any:
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    agent = Agent(TestModel(call_tools=[call_tool]))

    @agent.tool_plain
    def get_weather(city: str) -> str:
        """Get the current weather for a city (safe — allowed by policy)."""
        return f"Weather in {city}: 22C, partly cloudy (mock response)"

    @agent.tool_plain
    def delete_records(path: str) -> str:
        """Delete records at a path (destructive — denied by policy)."""
        return f"Deleted records at {path}"

    @agent.tool_plain
    def send_email(to: str) -> str:
        """Send an email (requires approval — pending then denied offline)."""
        return f"Email sent to {to}"

    return agent
```

The local policy engine simulates gateway enforcement, returning decisions in the gateway wire format (`src/policy.py`):

```python
class LocalPolicyEngine:
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

Pending tools route to `wait_for_tool_approval`, which denies them offline because no approver is available (`src/policy.py`):

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

!!! note "Pydantic AI version support"
    The adapter auto-detects the tool-execution hook across versions: it patches `pydantic_ai.tools.Tool._run` on `<0.3.0`, and `AbstractToolset.call_tool` (plus the concrete toolsets that override it) on `>=0.3.0`, where that internal entry point was renamed. The **tested line is `pydantic-ai>=0.3.0`** — the SDK's own dev/test group pins it, so it is the version exercised in CI. Earlier `0.1.x`–`0.2.x` releases still work through the `Tool._run` hook but are not continuously tested. See [Framework compatibility](../compatibility/frameworks.md) for the full matrix.

!!! note "Offline TestModel"
    The agent is driven by Pydantic AI's built-in `TestModel`, so the demo runs deterministically with no API key and no network. No running Agent Assembly gateway is required for the offline demo.

!!! tip "Troubleshooting"
    - `ModuleNotFoundError: agent_assembly` → run `uv sync` first.
    - `ModuleNotFoundError: pydantic_ai` → run `uv sync`; `pydantic-ai` is a required dependency.
    - Governance hooks do not fire → ensure `pydantic-ai` resolves within the supported range (`>=0.1.0`; `>=0.3.0` is the tested line).
    - `PolicyViolationError` in tests → expected; the deny/pending policy rules are intentional.

To move to production mode: start an Agent Assembly gateway (or use your SaaS workspace URL), copy `.env.example` to `.env` and fill in credentials, swap `TestModel` for a real model (e.g. `openai:gpt-4o`) and set `OPENAI_API_KEY`, then run with the gateway environment variables:

```bash
AGENT_ASSEMBLY_GATEWAY_URL=http://localhost:8080 \
AGENT_ASSEMBLY_API_KEY=your-key \
uv run python src/main.py
```

In production, `init_assembly()` auto-detects Pydantic AI and registers the adapter automatically, and the gateway enforces the policy rules — replacing `LocalPolicyEngine` with the gateway-backed interceptor.

## Expected behavior

```
==============================================================
  Agent Assembly — Pydantic AI Governed Agent Demo
==============================================================

Initializing Agent Assembly (gateway: http://localhost:8080, sdk-only mode)...
  Agent:    pydantic-ai-demo-agent
  Gateway:  http://localhost:8080
  Mode:     sdk-only (offline demo)

Policy rules (local simulation of gateway policy):
  DENY    — delete_records, write_file  (destructive operations)
  PENDING — send_email                  (requires human approval)
  ALLOW   — everything else

Running governed tool calls (driven offline by TestModel):
--------------------------------------------
  → agent run that calls get_weather
     ✅ ALLOWED  — get_weather executed (mock response)

  → agent run that calls delete_records
     ❌ BLOCKED  — Tool 'delete_records' blocked by governance policy: Tool 'delete_records' is blocked by policy rule 'deny_destructive_operations'.

  → agent run that calls send_email
     ❌ BLOCKED  — Tool 'send_email' rejected during approval: Tool 'send_email' requires approval, but no approver is available in offline mode.

Assembly context shut down.
```

## Links

- [Example directory](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python/pydantic-ai)
- [Example README](https://github.com/ai-agent-assembly/agent-assembly-examples/blob/master/python/pydantic-ai/README.md)
- [Pydantic AI documentation](https://ai.pydantic.dev/)
