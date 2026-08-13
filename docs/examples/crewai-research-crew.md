# CrewAI — multi-agent research crew

A three-agent CrewAI-style research crew (researcher → writer → critic) governed by Agent Assembly, where every governed tool call is attributed to the acting agent with the full delegation chain captured on each audit event by the demo's own `CrewPolicyEngine`. The SDK layer records nothing itself (AAASM-5731).

## What this example demonstrates

- A three-agent crew: **researcher → writer → critic**, each with a distinct role.
- **Agent-delegation tracking** — the demo's `CrewPolicyEngine` records an `AuditEvent` per governed call whose `call_stack` is the delegation chain (`parent → agent → tool`), built from the SDK's real `agent_assembly.types.AuditEvent` and `CallStackNode`. The types are the SDK's; the recording is the demo's.
- **Multi-agent governance** under one policy:
    - **File-write approval** — any agent that attempts `write_file` is gated; the decision is `pending` until an approver signs off (rejected in this demo).
    - **Shared daily budget** — tool calls across all three agents are metered against a single `$2.00 / day` cap.
- `--mock` mode: the whole crew runs offline with **no `crewai` install and no API keys**, so CI can run it.

## The framework / library

This example governs a [CrewAI](https://docs.crewai.com/)-style multi-agent crew.

Dependency pins from `pyproject.toml`:

- `agent-assembly>=0.0.1a2` — the Agent Assembly Python SDK (always required).
- The optional `live` extra pulls in `crewai>=0.30.0` — needed only for the real-crew integration. The `--mock` demo (what CI runs) needs none of it; it replays the crew's delegation trajectory offline.
- The `dev` extra provides `pytest>=8.0.0` and `pytest-mock>=3.14.0`.

The package requires Python `>=3.12`.

## How it works

`main()` initializes the SDK with `init_assembly(...)` in `mode="sdk-only"`, passing `agent_id="crewai-research-crew"` and a `gateway_url` that defaults to `http://localhost:8080`. The returned context manager exposes `ctx.client` and `ctx.network_mode`.

Governance is simulated locally by `CrewPolicyEngine` (from `src/policy.py`), wired into the SDK through `AssemblyCallbackHandler(interceptor=policy)`. The crew is described in `src/crew.py` as three `CrewMember` dataclasses, and the offline run replays a scripted `MOCK_TRAJECTORY` of `CrewStep`s. For each step, `main()` calls `policy.acting_as(agent, parent)` to set the active crew member, then fires `handler.on_tool_start(...)`.

`CrewPolicyEngine` applies the same policy to every agent's tool calls:

- **File-write approval gate.** `check_tool_start` returns `status="pending"` for any tool in `APPROVAL_REQUIRED_TOOLS` (`{"write_file"}`), deferring to `wait_for_tool_approval`. There, `MockApprover.decide(...)` returns its `auto_approve` value — `False` in the demo — so the decision becomes `deny` with the message that the crew may not persist files without sign-off.
- **Shared daily budget.** Non-approval tools are priced from `TOOL_COSTS` (defaulting to `$0.01`) and charged against one `BudgetTracker` shared across all three agents; if the cap is exhausted the call is denied.
- **Delegation call stack.** Every allow/deny call is recorded by `_emit(...)`, which constructs a `CallStackNode` chain `parent → acting agent → tool` and appends an `AuditEvent` (carrying `call_stack` plus `crew_member` / `delegated_by` labels) to `policy.audit_events`.

After the trajectory, `main()` prints each recorded `AuditEvent` (decision, action type, and the flattened delegation chain) and the final shared budget via `policy.budget.status()`.

## Prerequisites & running it

See [Preparing the runtime environment](preparing-the-runtime-environment.md) for the shared prerequisites.

Then, from the example directory:

```bash
cd python/crewai-research-crew
uv sync --extra dev
uv run python src/main.py --mock
```

`--mock` replays the scripted crew delegation trajectory offline — no gateway, no `crewai`, and no API keys. The example also auto-falls back to mock mode whenever `OPENAI_API_KEY` is unset.

To drive the real CrewAI crew instead, install the optional `live` extra:

```bash
pip install -e '.[live]'
```

## Code walkthrough

The shared budget, approval gate, and required-approval tool set are declared at module scope in `src/policy.py`:

```python
#: Shared per-day spend ceiling (USD) across every agent in the crew.
DAILY_BUDGET_USD: float = 2.00

#: Per-call cost model (USD) used to meter spend in offline mode.
TOOL_COSTS: dict[str, float] = {
    "web_search": 0.05,
    "compose_report": 0.10,
    "review_text": 0.05,
    "write_file": 0.00,
}

#: Tools that require human approval before execution.
APPROVAL_REQUIRED_TOOLS: frozenset[str] = frozenset({"write_file"})
```

`check_tool_start` routes a `write_file` to the approval path and meters everything else against the shared budget:

```python
# 1. File-write approval gate — defer to wait_for_tool_approval.
if tool_name in APPROVAL_REQUIRED_TOOLS:
    return {"status": "pending", "reason": (...)}

# 2. Shared daily budget — deny once the crew's cap is exhausted.
cost = TOOL_COSTS.get(tool_name, 0.01)
if not self.budget.can_afford(cost):
    self._emit(tool_name, "deny")
    return {"status": "deny", "reason": (...)}

self.budget.charge(cost)
self._emit(tool_name, "allow")
```

Each governed call records an `AuditEvent` whose `call_stack` is the delegation chain:

```python
tool_node = CallStackNode(id=str(uuid4()), kind="tool", label=tool_name)
acting_node = CallStackNode(
    id=str(uuid4()), kind="llm", label=self._acting_agent, children=[tool_node]
)
if self._parent_agent is not None:
    stack = [CallStackNode(id=str(uuid4()), kind="llm",
                           label=self._parent_agent, children=[acting_node])]
else:
    stack = [acting_node]
```

The crew members and their scripted delegation trajectory live in `src/crew.py`:

```python
CREW: tuple[CrewMember, ...] = (RESEARCHER, WRITER, CRITIC)

MOCK_TRAJECTORY: tuple[CrewStep, ...] = (
    CrewStep("researcher", None, "web_search", {"query": "agent governance"}),
    CrewStep("researcher", None, "web_search", {"query": "interception layers"}),
    CrewStep("writer", "researcher", "compose_report", {"section": "summary"}),
    CrewStep("critic", "writer", "review_text", {"target": "summary"}),
    # The critic tries to persist the report — file writes require approval.
    CrewStep("critic", "writer", "write_file", {"path": "report.md"}),
)
```

## Notes & caveats

!!! tip "Mock mode needs no `crewai` and no API keys"
    The `--mock` path replays the crew's delegation trajectory entirely offline — no gateway, no `crewai` install, and no LLM provider key — which is exactly what makes it safe to run in CI.

!!! note "Seeing the approval path succeed"
    `MockApprover` rejects file writes by default (`auto_approve=False`), so the demo shows the `write_file` request denied. To see the approval path succeed instead, construct the policy with an auto-approving approver — `MockApprover(auto_approve=True)` — and the `write_file` event then records an `allow` decision.

## Expected behavior

Running `uv run python src/main.py --mock` produces:

```
================================================================
  Agent Assembly — CrewAI Multi-Agent Research Crew
================================================================

Initializing Agent Assembly (gateway: http://localhost:8080, sdk-only mode)...
  Agent:    crewai-research-crew
  Gateway:  http://localhost:8080
  Mode:     sdk-only (mock (offline))

Crew members:
  • researcher  — Senior Research Analyst
  • writer      — Technical Writer
  • critic      — Editorial Critic

Crew policy (local simulation of gateway policy):
  APPROVAL — any agent attempting a file write must be approved
  BUDGET   — $2.00 / day, shared across all agents
  TRACK    — every call recorded with its delegation call stack

Running crew delegation trajectory:
----------------------------------------------
  [researcher]  (crew entry agent)
    → web_search({"query": "agent governance"})
       ✅ ALLOWED

  [researcher]  (crew entry agent)
    → web_search({"query": "interception layers"})
       ✅ ALLOWED

  [writer]  (delegated by researcher)
    → compose_report({"section": "summary"})
       ✅ ALLOWED

  [critic]  (delegated by writer)
    → review_text({"target": "summary"})
       ✅ ALLOWED

  [critic]  (delegated by writer)
    → write_file({"path": "report.md"})
       ❌ BLOCKED  — Approval for 'write_file' by 'critic' was rejected — the crew may not persist files without sign-off.

Delegation-aware audit events recorded this run (by the demo's own handler — the SDK layer produces none, AAASM-5731):
----------------------------------------------
  ✅ allow web_search      chain: researcher → web_search
  ✅ allow web_search      chain: researcher → web_search
  ✅ allow compose_report  chain: researcher → writer → compose_report
  ✅ allow review_text     chain: writer → critic → review_text
  ❌ deny  write_file      chain: writer → critic → write_file

Final crew budget: spent=$0.25 / limit=$2.00 (12%)

Assembly context shut down.
```

Governance-output walkthrough:

| Step | Acting agent | Delegated by | Governance control | Outcome |
|---|---|---|---|---|
| `web_search` | researcher | — (entry) | shared budget | **ALLOWED**, `$0.05` |
| `web_search` | researcher | — (entry) | shared budget | **ALLOWED**, `$0.05` |
| `compose_report` | writer | researcher | shared budget | **ALLOWED**, `$0.10` |
| `review_text` | critic | writer | shared budget | **ALLOWED**, `$0.05` |
| `write_file` | critic | writer | file-write approval | **BLOCKED** — approval rejected |

The `chain:` column in the audit replay is the delegation call stack each `AuditEvent` carries: it shows which agent delegated to which, down to the tool. This is the agent-delegation tracking that distinguishes multi-agent governance from single-agent governance — a real gateway persists the same call stack so an operator can see exactly who delegated a blocked action.

## Links

- [Example directory](https://github.com/ai-agent-assembly/examples/tree/master/python/crewai-research-crew)
- [Example README](https://github.com/ai-agent-assembly/examples/blob/master/python/crewai-research-crew/README.md)
- [CrewAI documentation](https://docs.crewai.com/)
