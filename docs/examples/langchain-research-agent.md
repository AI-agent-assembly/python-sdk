# LangChain — research agent

A richer ReAct variant of the basic LangChain example, governing a web-search-and-calculator research agent under a single *balanced* policy.

## What this example demonstrates

This example initializes Agent Assembly with `init_assembly()` in `sdk-only` mode and runs a ReAct-style research trajectory over two tools — `web_search` and `calculator` — under a **balanced policy** that bundles four controls at once:

- **Network allowlist** — outbound egress is only allowed to `*.openai.com`.
- **Daily budget** — tool calls are metered against a `$1.00 / day` cap.
- **Tool-call logging** — the demo appends every governed call to its own in-process `audit_log`. That log is the demo's, not the SDK's: this example supplies its own handler and runs without a runtime, so the SDK's own sink is not what fills it (AAASM-5750).
- **Credential-leak block** — any tool input carrying a secret is denied.

It also includes a credential-leak demo that uses a **SAFE, FAKE** key (`sk-FAKE...`) — never a real secret — to show the leak rule firing. Finally, `--mock` mode runs the whole demo offline with no API keys, so CI can run it.

## The framework / library

This example is built on [LangChain](https://python.langchain.com/). The tools are defined with LangChain's `@tool` decorator (`langchain_core.tools.tool`), and the governance layer hooks into LangChain via Agent Assembly's `AssemblyCallbackHandler` callback handler.

Version pins from `pyproject.toml`:

| Dependency | Version |
|---|---|
| `agent-assembly` | `>=0.0.1a2` |
| `langchain-core` | `>=0.2.0` |
| Python | `>=3.12` |

Dev extras pin `pytest>=8.0.0` and `pytest-mock>=3.14.0`.

## How it works

`main.py` opens an Agent Assembly context with `init_assembly()` in `sdk-only` mode:

```python
with init_assembly(
    gateway_url=gateway_url,
    api_key=api_key,
    agent_id="langchain-research-agent",
    mode="sdk-only",
) as ctx:
    ...
```

Inside the context it constructs a `BalancedPolicyEngine` and wires it into LangChain through `AssemblyCallbackHandler(interceptor=policy)`.

The agent then replays a scripted **ReAct trajectory** — the steps a real LLM-driven agent would emit while researching its question — over the two tools `web_search` and `calculator`. Each step goes through `_run_governed_call`, which fires the handler's `on_tool_start` callback before invoking the tool. The `BalancedPolicyEngine.check_tool_start` method evaluates the rules in priority order:

1. **Credential-leak block** (highest priority, fail-closed) — if the input matches any credential pattern (e.g. `sk-...`, `AKIA...`, `api_key=...`, `secret/password/token=...`), the call is denied.
2. **Network allowlist** — any `http(s)://` URL in the input has its host extracted and checked against `NETWORK_ALLOWLIST` (`*.openai.com`, `openai.com`); a non-allowlisted host is denied.
3. **Daily budget** — the per-call cost (`web_search` = `$0.02`, `calculator` = `$0.00`) is checked against the remaining `$1.00 / day` cap; an exhausted budget denies the call.
4. **Tool-call logging** — on an allow, the budget is charged and the decision is recorded.

Every call, allowed or denied, is appended to `audit_log`. A denied call surfaces as a `ToolExecutionBlockedError` raised by the callback handler, which `_run_governed_call` catches and prints as `❌ BLOCKED`. At the end of the run the demo replays the full audit trail and the final budget total.

## Prerequisites & running it

See [Preparing the runtime environment](preparing-the-runtime-environment.md) for the shared prerequisites.

Then, from the examples repository:

```bash
cd python/langchain-research-agent
uv sync --extra dev
uv run python src/main.py --mock
```

`--mock` replays a scripted ReAct trajectory offline with no API keys. The example also auto-falls back to mock mode whenever `OPENAI_API_KEY` is unset.

## Code walkthrough

The balanced policy configuration (`policy.py`):

```python
#: Outbound network egress is only permitted to hosts matching this allowlist.
NETWORK_ALLOWLIST: tuple[str, ...] = ("*.openai.com", "openai.com")

#: Per-day spend ceiling, in USD. Tool calls are metered against this cap.
DAILY_BUDGET_USD: float = 1.00

#: Per-call cost model (USD) used to meter spend in offline mode.
TOOL_COSTS: dict[str, float] = {
    "web_search": 0.02,
    "calculator": 0.00,
}
```

The rule evaluation order in `check_tool_start` — credential-leak first, then allowlist, then budget (`policy.py`):

```python
# 4. Credential-leak block — highest priority, fail closed.
if _contains_credential(input_str):
    reason = (
        f"Tool '{tool_name}' input contains a credential and is blocked "
        "by policy rule 'block_credential_leak'."
    )
    self._record(tool_name, "deny", reason)
    return {"status": "deny", "reason": reason}

# 1. Network allowlist — deny egress to non-allowlisted hosts.
match = re.search(r"https?://[^\s\"']+", input_str)
if match:
    host = _extract_host(match.group(0))
    if not _host_allowed(host):
        reason = (
            f"Tool '{tool_name}' attempted egress to '{host}', which is "
            "not on the network allowlist (*.openai.com)."
        )
        self._record(tool_name, "deny", reason)
        return {"status": "deny", "reason": reason}
```

The scripted ReAct trajectory replayed in `--mock` mode (`main.py`):

```python
_MOCK_REACT_STEPS: list[tuple[str, str]] = [
    ("web_search", '{"query": "speed of light"}'),
    ("web_search", '{"query": "population of France"}'),
    ("calculator", '{"expression": "299792458 / 68000000"}'),
    # An egress attempt to a host NOT on the allowlist — blocked by policy.
    ("web_search", '{"query": "fetch https://evil-exfil.example.com/leak"}'),
]
```

The governed call: it fires the callback before invoking the tool and catches a block (`main.py`):

```python
def _run_governed_call(handler, tool_name, input_str):
    print(f"  → {tool_name}({input_str})")
    try:
        handler.on_tool_start(
            serialized={"name": tool_name, "type": "tool"},
            input_str=input_str,
            run_id=uuid4(),
        )
        result = _TOOLS[tool_name].invoke(json.loads(input_str))
        print(f"     ✅ ALLOWED  — {result}")
    except ToolExecutionBlockedError as exc:
        print(f"     ❌ BLOCKED  — {exc}")
    print()
```

## Notes & caveats

!!! warning "The credential-leak demo uses a SAFE FAKE key"
    The credential-leak step submits `sk-FAKE0000DEMO0000NOTAREALKEY0000` — a deliberately fake, non-functional key. It is used only to show the credential-leak policy rule firing, and is never a real secret.

!!! tip "`--mock` runs offline"
    `--mock` replays the scripted ReAct trajectory offline with no API keys and no real network access, which is what CI runs. The example also auto-falls back to mock mode whenever `OPENAI_API_KEY` is unset.

## Expected behavior

```
================================================================
  Agent Assembly — LangChain ReAct Research Agent
================================================================

Initializing Agent Assembly (gateway: http://localhost:8080, sdk-only mode)...
  Agent:    langchain-research-agent
  Gateway:  http://localhost:8080
  Mode:     sdk-only (mock (offline))

Balanced policy (local simulation of gateway policy):
  ALLOWLIST — outbound egress to *.openai.com, openai.com
  BUDGET    — $1.00 / day, metered per tool call
  LOG       — every tool call recorded as an audit event
  BLOCK     — any tool input that leaks a credential

Running ReAct research trajectory:
----------------------------------------------
  → web_search({"query": "speed of light"})
     ✅ ALLOWED  — The speed of light in vacuum is 299792458 metres per second.

  → web_search({"query": "population of France"})
     ✅ ALLOWED  — France has a population of approximately 68000000 people.

  → calculator({"expression": "299792458 / 68000000"})
     ✅ ALLOWED  — 299792458 / 68000000 = 4.40871

  → web_search({"query": "fetch https://evil-exfil.example.com/leak"})
     ❌ BLOCKED  — Tool 'web_search' attempted egress to 'evil-exfil.example.com', which is not on the network allowlist (*.openai.com).

Credential-leak demo (SAFE FAKE key):
----------------------------------------------
  → web_search({"query": "summarize using api_key=sk-FAKE0000DEMO0000NOTAREALKEY0000"})
     ❌ BLOCKED  — Tool 'web_search' input contains a credential and is blocked by policy rule 'block_credential_leak'.

Governance events recorded this run:
----------------------------------------------
  ✅ web_search   allow — allowed (charged $0.02; spent=$0.02 / limit=$1.00 (2%))
  ✅ web_search   allow — allowed (charged $0.02; spent=$0.04 / limit=$1.00 (4%))
  ✅ calculator   allow — allowed (charged $0.00; spent=$0.04 / limit=$1.00 (4%))
  ❌ web_search   deny  — Tool 'web_search' attempted egress to 'evil-exfil.example.com', which is not on the network allowlist (*.openai.com).
  ❌ web_search   deny  — Tool 'web_search' input contains a credential and is blocked by policy rule 'block_credential_leak'.

Final budget: spent=$0.04 / limit=$1.00 (4%)

Assembly context shut down.
```

### How to read the governance events

| Event | Governance control | Outcome |
|---|---|---|
| `web_search("speed of light")` | tool-call capture + budget | **ALLOWED**, charged `$0.02` |
| `web_search("population of France")` | tool-call capture + budget | **ALLOWED**, charged `$0.02` |
| `calculator(...)` | tool-call capture + budget | **ALLOWED**, `$0.00` (local compute) |
| `web_search(... evil-exfil.example.com ...)` | network allowlist | **BLOCKED** — host not on `*.openai.com` |
| `web_search(... api_key=sk-FAKE... )` | credential-leak block | **BLOCKED** — secret detected in input |

The final block replays the full audit trail and the running budget total — the governance evidence a real gateway would persist server-side.

## Links

- [Example directory](https://github.com/ai-agent-assembly/examples/tree/master/python/langchain-research-agent)
- [Example README](https://github.com/ai-agent-assembly/examples/blob/master/python/langchain-research-agent/README.md)
- [LangChain documentation](https://python.langchain.com/)
