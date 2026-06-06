# Framework examples

Agent Assembly governs *third-party* agent frameworks without those frameworks needing to be
aware of it. You call `init_assembly()` once; the SDK detects which supported frameworks are
importable in your process and installs governance hooks for each, in priority order (see
[Architecture](../architecture/index.md)).

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
**Runnable example** column reflects whether a complete, validated example exists in this
repository today.

| Framework | Adapter | Runnable example |
| --- | --- | --- |
| LangChain | `agent_assembly.adapters.langchain` | ✅ Validated — see [Quick start](#langchain-quick-start) below (runs offline against a mock LLM). |
| LangGraph | `agent_assembly.adapters.langgraph` | ⏳ Planned — adapter ships; wraps `StateGraph.compile()`. |
| CrewAI | `agent_assembly.adapters.crewai` | ⏳ Planned — adapter ships. |
| OpenAI Agents | `agent_assembly.adapters.openai_agents` | ⏳ Planned — adapter ships. |
| Pydantic AI | `agent_assembly.adapters.pydantic_ai` | ⏳ Planned — adapter ships. |
| Google ADK | `agent_assembly.adapters.google_adk` | ⏳ Planned — adapter ships. |
| MCP servers | `agent_assembly.adapters.mcp` | ⏳ Planned — adapter ships. |

!!! note "Adapter present vs. example present"
    A ⏳ row means the **adapter is implemented and registered** — `init_assembly()` will detect
    and hook the framework if it's installed — but a curated, end-to-end runnable example is
    not yet vendored in `examples/`. Contributions adding one are welcome; see
    [CONTRIBUTING.md](https://github.com/AI-agent-assembly/python-sdk/blob/master/CONTRIBUTING.md).

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

The same snippet lives in the repository [README](https://github.com/AI-agent-assembly/python-sdk#quick-start)
and is the canonical, validated example. See the [`examples/`](https://github.com/AI-agent-assembly/python-sdk/tree/master/examples)
directory for additional runnable scripts and their status.
