# Quick Start

Govern your first agent in about five minutes. By the end you'll have a LangChain agent whose
tool calls pass through the Agent Assembly policy gate — and it runs **offline**, against a
mock LLM, so you need no API keys and no network access to the outside world.

## 1. Install

The package is published on PyPI as
[`{{ aa.python_sdk.package_name }}`]({{ aa.urls.pypi }}) (current version:
`{{ aa.python_sdk.version }}`).

=== "pip"

    ```bash
    {{ aa.commands.install_pip }}            # pure-Python SDK
    {{ aa.commands.install_pip_runtime }} # SDK + bundled aasm runtime binary (platform wheel)
    ```

=== "uv"

    ```bash
    {{ aa.commands.install_uv }}
    ```

`{{ aa.python_sdk.package_name }}` is the pure-Python client.
`{{ aa.python_sdk.package_name }}[runtime]` additionally pulls a platform wheel
(`manylinux`, `macosx`) that bundles the `{{ aa.python_sdk.cli_name }}`
gateway/runtime binary, so a local gateway is available without a separate install.

## 2. Point the SDK at a gateway

`init_assembly()` needs to reach a **gateway** — the policy brain that returns allow/deny
decisions. You have three options:

- **Let the SDK auto-start one.** Call `init_assembly()` with no `gateway_url`; the SDK probes
  `http://localhost:7391` and, if nothing answers, runs `aasm start --mode local --foreground`
  for you. This needs the `aasm` binary on your `PATH` (the `agent-assembly[runtime]` extra
  provides it).
- **Run one yourself** with `aasm start --mode local --foreground` in a separate terminal. For
  a full gateway walkthrough, see the core
  [Run the gateway](https://docs.agent-assembly.com/core/getting-started/) guide.
- **Pass an explicit URL**, as the example below does.

See [Configuration](configuration.md) for the full URL/key resolution chain (`7391` is the
local default port).

## 3. Govern your first agent

This example imports LangChain alongside the SDK, so install both:

```bash
{{ aa.commands.install_pip }} langchain langchain-community
```

Then run:

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

## What just happened

1. **`init_assembly()` wired in governance.** It registered the agent (`quickstart-agent`)
   with the gateway and auto-loaded the LangChain adapter — every tool call from this point
   on is routed through the policy gate.
2. **The `FakeListLLM` replays canned responses**, so the agent runs entirely offline with no
   real LLM.
3. **The `whoami` tool call was governed.** The adapter intercepted `BaseTool._run` and asked
   the gateway for a verdict before the tool actually ran.
4. **The `with` block tore everything down on exit** — adapter hooks were unwound and the
   gateway connection closed, leaving the process exactly as it was before.

### Expected output

```text
alice is in engineering
```

If instead you see a `ToolExecutionBlockedError`, that is not a bug — the gateway's policy
denied the `whoami` call. That's the product working. See
[Handling allow/deny decisions](guides/handling-decisions.md) for how to catch and respond to
those, and [Troubleshooting](troubleshooting.md) if `init_assembly()` itself raised.

## `mode="sdk-only"` — why this example uses it

`mode="sdk-only"` is the in-process-only interception layer: the framework adapter enforces on
tool calls, with no network sidecar to start. It's the most portable mode and the best choice
for deterministic, offline examples and tests. The other modes (`auto`, `proxy`, `ebpf`) add
network/kernel interception — see [Core Concepts → Modes](concepts/index.md#runtime-modes).

## Next steps

- **[Core Concepts](concepts/index.md)** — the adapter pattern, the `init_assembly()`
  lifecycle, and the modes/enforcement model.
- **[Examples](examples/index.md)** — wire the SDK into the framework you actually use.
- **[Configuration](configuration.md)** — drop the hard-coded URL and key; let the resolver
  chain find them.
