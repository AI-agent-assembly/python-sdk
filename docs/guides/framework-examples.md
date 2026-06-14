# Framework examples

Agent Assembly governs *third-party* agent frameworks without those frameworks needing to be
aware of it. You call `init_assembly()` once; the SDK detects which supported frameworks are
importable in your process and installs governance hooks for each, in priority order (see
[Core Concepts](../concepts/index.md#the-adapter-pattern)).

## The universal pattern

The integration is the same for every framework — there is no per-framework setup call:

```python
from agent_assembly import init_assembly

with init_assembly(
    gateway_url="http://localhost:7391",
    api_key="dev-key",
    agent_id="my-agent",
    mode="sdk-only",
):
    # Build and run your agent exactly as you normally would.
    # Every tool call now passes through the policy gate and is audited.
    ...
```

Inside the `with` block, the relevant adapter has monkey-patched the framework's tool-call
entry points. On exit, all hooks are removed in reverse order.

## Supported frameworks

Each framework below ships an adapter under `agent_assembly/adapters/`. The
**Runnable example** column reflects whether a complete, validated example exists today —
either inline in this guide or as a curated script in the central
[`agent-assembly-examples`](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python)
repository.

| Framework | Adapter | Runnable example |
| --- | --- | --- |
| LangChain | `agent_assembly.adapters.langchain` | ✅ Validated — see [Quick start](#langchain-quick-start) below (runs offline against a mock LLM), plus [`langchain-basic-agent`](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python/langchain-basic-agent) and [`langchain-research-agent`](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python/langchain-research-agent). |
| LangGraph | `agent_assembly.adapters.langgraph` | ✅ Validated — see [`langgraph`](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python/langgraph) (state-graph governance; wraps `StateGraph.compile()`). |
| CrewAI | `agent_assembly.adapters.crewai` | ✅ Validated — see [`crewai-research-crew`](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python/crewai-research-crew) (multi-agent crew). |
| OpenAI Agents | `agent_assembly.adapters.openai_agents` | ✅ Validated — see [`openai-agents-sdk`](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python/openai-agents-sdk). |
| Pydantic AI | `agent_assembly.adapters.pydantic_ai` | ✅ Validated — see [`pydantic-ai`](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python/pydantic-ai). |
| Google ADK | `agent_assembly.adapters.google_adk` | ✅ Validated — see [`google-adk`](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python/google-adk). |
| MCP servers | `agent_assembly.adapters.mcp` | ⏳ Planned — adapter ships; a curated example is not yet vendored. |

!!! note "Adapter present vs. example present"
    Every framework above has an **adapter that is implemented and registered** — `init_assembly()`
    will detect and hook the framework whenever it's installed, regardless of the example status.
    A ✅ row additionally has a curated, end-to-end runnable example you can clone and run. A ⏳ row
    (currently only MCP servers) means the adapter ships but a runnable example is not yet vendored.
    Contributions adding one are welcome; see
    [CONTRIBUTING.md](https://github.com/ai-agent-assembly/python-sdk/blob/master/CONTRIBUTING.md).

## LangChain quick start

A governed LangChain ReAct agent that runs **offline** against a mock LLM — no real API keys
and no network calls. Install the SDK plus LangChain:

```bash
pip install agent-assembly langchain langchain-community
```

```python
from langchain.agents import AgentExecutor, create_react_agent
from langchain.tools import Tool
from langchain_community.llms import FakeListLLM
from langchain_core.prompts import PromptTemplate

from agent_assembly import init_assembly

with init_assembly(
    gateway_url="http://localhost:7391",
    api_key="dev-key",
    agent_id="quickstart-agent",
    mode="sdk-only",
):
    llm = FakeListLLM(responses=[
        "Thought: I should look up the user.\nAction: whoami\nAction Input: alice\n",
        "Thought: I have the answer.\nFinal Answer: alice is in engineering\n",
    ])
    tools = [Tool(name="whoami", func=lambda name: f"{name} is in engineering", description="who")]
    prompt = PromptTemplate.from_template(
        "Use the tools.\n{tools}\nTool names: {tool_names}\nQ: {input}\n{agent_scratchpad}"
    )
    executor = AgentExecutor(agent=create_react_agent(llm, tools, prompt), tools=tools, max_iterations=2)
    print(executor.invoke({"input": "Which team is alice on?"})["output"])
```

The same snippet lives in the repository [README](https://github.com/ai-agent-assembly/python-sdk#quick-start)
and is the canonical, validated example. See the [`examples/`](https://github.com/ai-agent-assembly/python-sdk/tree/master/examples)
directory for additional runnable scripts and their status.
