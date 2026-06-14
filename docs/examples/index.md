# Examples

End-to-end, runnable examples that govern real AI agent frameworks with Agent Assembly. Each
example is a self-contained project in the
[`agent-assembly-examples`](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python)
repository, and each page below walks through what it demonstrates, how the `init_assembly()`
adapter flow wires the framework, an annotated code walkthrough, and the expected output.

!!! tip "Everything here runs offline"
    Every example is designed to run with **no API keys and no running gateway** — it executes
    in `sdk-only` mode and simulates the gateway's policy enforcement locally. Connecting to a
    real gateway is an optional production-mode step documented on each page.

## Start here

1. [Preparing the runtime environment](preparing-the-runtime-environment.md) — the shared
   prerequisites, install steps, and run commands that apply to **every** example. Read this
   first.
2. [Framework support](framework-support.md) — the adapter ↔ example status reference and the
   universal `init_assembly()` pattern.

## The examples

| Example | Framework | Governance focus |
|---|---|---|
| [LangChain — basic agent](langchain-basic-agent.md) | LangChain | Allow / deny / pending on tool calls via `AssemblyCallbackHandler`. |
| [LangChain — research agent](langchain-research-agent.md) | LangChain | A *balanced* policy: network allowlist, daily budget, tool-call logging, and credential-leak blocking. |
| [LangGraph — node-level governance](langgraph.md) | LangGraph | Node-level hooks on a compiled `StateGraph`; a denied tool halts the graph mid-execution. |
| [CrewAI — multi-agent research crew](crewai-research-crew.md) | CrewAI | Multi-agent delegation tracking, file-write approval, and a shared budget across agents. |
| [OpenAI Agents SDK](openai-agents-sdk.md) | OpenAI Agents SDK | Approval-gated and denied tool calls, intercepting `FunctionTool.__call__`. |
| [Pydantic AI](pydantic-ai.md) | Pydantic AI | Tool-call governance driven offline by the built-in `TestModel`. |
| [Google ADK](google-adk.md) | Google ADK | A scripted offline tool trajectory governing `BaseTool.run_async` — no cloud credentials. |
| [LlamaIndex — manual tool policy](llamaindex-tool-policy.md) | LlamaIndex | The manual wrapper pattern (`GovernedToolRunner`) for a framework with no native adapter. |
| [Custom tool policy (no framework)](custom-tool-policy.md) | — | Govern plain Python functions with the minimal `governed()` helper — no AI framework required. |

## How the examples fit together

- **No native adapter?** [Custom tool policy](custom-tool-policy.md) shows the minimal
  `governed()` building block; [LlamaIndex — manual tool policy](llamaindex-tool-policy.md)
  builds on it with `GovernedToolRunner`. Use these patterns for any framework Agent Assembly
  does not hook automatically.
- **Native adapter?** The LangChain, LangGraph, CrewAI, OpenAI Agents, Pydantic AI, and Google
  ADK examples each rely on `init_assembly()` detecting the framework and installing its
  governance hooks for you — see [Framework support](framework-support.md) for the full
  adapter list and priority order.
