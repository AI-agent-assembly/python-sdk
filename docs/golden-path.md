# Start Here: The Golden Path

**New here? Read this first.** This is the map, not the manual. It walks you through the
whole journey of governing a Python agent with Agent Assembly — from install to a running,
observable, tunable governed agent — in order, and links you to the one canonical page that
owns each step. Nothing on this page is a command to copy; each step points you to the page
that actually teaches it, so instructions never drift out of sync.

Follow the steps top to bottom the first time. Later, use it as a table of contents for the
end-to-end flow.

---

## 1. What you'll achieve

By the end of this path you'll have a **governed AI agent whose tool calls you can allow,
deny, observe, and control — without changing the agent's logic**. You wrap your existing
LangChain / CrewAI / LangGraph / … agent in a single `init_assembly()` call, and from then
on every tool call is checked against policy, allowed or denied, and recorded. The agent code
stays exactly as you wrote it.

## 2. Before you begin

Skim what the SDK is and where it fits before installing: it's an in-process governance shim
plus a client that talks to the Agent Assembly gateway (the policy brain). Prerequisites and
the mental model live in the **[Introduction](index.md)**, and the shared prerequisites for
every runnable example are in **[Preparing the runtime environment](examples/preparing-the-runtime-environment.md)**.

→ **[Introduction](index.md)**

## 3. Install

Add the SDK to your environment (with the optional `runtime` extra if you want the local
gateway binary). The exact install command and its variants live in the Quick Start.

→ **[Quick Start → Install](quick-start.md#1-install)**

## 4. Connect to the gateway

`init_assembly()` needs to reach a gateway. You can let the SDK auto-start a local one, run
one yourself, or pass an explicit URL — and the same page covers the API-key and URL
resolution chain, runtime modes, and enforcement modes.

→ **[Quick Start → Point the SDK at a gateway](quick-start.md#2-point-the-sdk-at-a-gateway)**
· **[Configuration](configuration.md)**

## 5. Your first governed action (allowed)

Wire `init_assembly()` into the framework you already use and watch an **allowed** tool call
run normally through the gate. The Quick Start's framework tabs give you the exact governance
slice for your framework.

→ **[Quick Start → Govern your first agent](quick-start.md#3-govern-your-first-agent)**

## 6. See a policy denial

Now trigger a call the policy forbids. A `deny` surfaces in your code as a raised
`ToolExecutionBlockedError` at the point the tool would have run — ordinary Python exception
handling. The decisions guide shows exactly which exception to catch and how.

→ **[Guides → Handling allow/deny decisions](guides/handling-decisions.md#catching-a-denial)**

## 7. Approvals (human-in-the-loop)

Some decisions aren't a flat allow/deny — they're *pending*, awaiting a human's approval
before the tool runs. This flow is surfaced through the same decision-handling path; the
framework examples for **OpenAI Agents** and **LangChain** demonstrate approval-gated and
pending tool calls today.

→ **[Guides → Handling allow/deny decisions](guides/handling-decisions.md)**
· **[Examples → OpenAI Agents SDK](examples/openai-agents-sdk.md)**

## 8. Observe your agent

Every tool call, prompt, and policy decision is emitted to the gateway with full agent
lineage. To read the audit trail and see your agent in the dashboard — the operator and
observability side — head to the documentation hub.

→ **[Documentation hub](https://docs.agent-assembly.com/)** (operator & observability, audit trail)

## 9. Tune governance

Change a policy and watch behavior change. Locally, `enforcement_mode` lets you dial the
posture from full `enforce` to a dry-run `observe` that records would-be violations without
blocking — a safe way to roll out policy. The full policy reference lives on the hub.

→ **[Configuration → Enforcement modes](configuration.md#enforcement-modes)**
· **[Documentation hub → policy reference](https://docs.agent-assembly.com/core/)**

## 10. Operate it

Governance has two sides: the developer arc you're on now, and the operator arc — running and
governing the gateway itself, managing policy, and reviewing audit. The operator walkthrough
lives on the hub.

→ **[Documentation hub → Operator path](https://docs.agent-assembly.com/core/)**

## 11. Explore framework examples

See the pattern applied end-to-end to real frameworks — LangChain, LangGraph, CrewAI, OpenAI
Agents, Pydantic AI, Google ADK, and more. Each example is self-contained and runs offline.

→ **[Examples](examples/index.md)**

## 12. You've experienced the core value

You've installed the SDK, connected it to a gateway, run an allowed call, seen a denial,
observed the audit trail, and tuned a policy — a governed agent whose tool calls you control,
without touching the agent's logic. **What's next:** apply the pattern to your other
frameworks via the [Examples](examples/index.md), move from local to production/SaaS, and read
the cross-cutting platform docs on the **[documentation hub](https://docs.agent-assembly.com/)**.

---

!!! tip "Two personas, two arcs"
    This page is the **developer** arc — wiring governance into an agent. There's a parallel
    **operator** arc — running the gateway, authoring policy, and reviewing the audit trail
    end-to-end. For the operator / end-to-end governance walkthrough, see the
    [documentation hub](https://docs.agent-assembly.com/).
