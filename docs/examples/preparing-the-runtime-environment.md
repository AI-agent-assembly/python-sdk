# Preparing the runtime environment

Every page in this section walks through a self-contained, cloneable example from the
[`agent-assembly-examples`](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python)
repository. The examples share the same prerequisites and the same run shape, so this page
collects everything you need **once** — each per-framework page then only lists what is
specific to that example.

!!! tip "Every example runs offline by default"
    All nine examples are designed to run **with no API keys and no running gateway**. They
    execute in `sdk-only` mode and simulate the gateway's policy enforcement locally, so you
    can clone, install, and run them on a laptop with no credentials. Connecting to a real
    gateway is an optional "production mode" step documented on each page.

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | `>= 3.12` | Every example targets Python 3.12+. |
| [uv](https://github.com/astral-sh/uv) | latest | The examples use `uv` for dependency management and running. `pip` also works. |
| Agent Assembly Python SDK | `>= 0.0.1a2` | Installed for you via each example's `pyproject.toml` (`agent-assembly>=0.0.1a2`). |
| Agent Assembly gateway | optional | **Not** required for the offline demos. Only needed for production mode. |

## Install the SDK

Each example declares `agent-assembly` as a dependency, so `uv sync` (below) pulls it in.
To install the SDK on its own in your own project:

```bash
pip install agent-assembly
```

Some examples need a framework extra alongside the SDK (for instance LangChain pulls in
`langchain-core`, LangGraph pulls in `langgraph`, CrewAI offers an optional `live` extra).
The exact dependency pins live in each example's `pyproject.toml` and are installed by
`uv sync` — you do not need to install them by hand.

## Clone the examples repository

The examples live in a dedicated repository. Clone it and change into the `python/`
directory:

```bash
git clone https://github.com/ai-agent-assembly/agent-assembly-examples.git
cd agent-assembly-examples/python
```

Each subdirectory under `python/` is a standalone project with its own `README.md`,
`pyproject.toml`, optional `.env.example`, and a `src/` entrypoint (`src/main.py`).

## Running an example

The flow is the same for every example — change into the example directory, install its
dependencies, then run its entrypoint:

```bash
cd python/<example-name>
uv sync --extra dev
uv run python src/main.py
```

`uv sync --extra dev` installs the runtime dependencies plus the `dev` extras (the test
tooling). The entrypoint is always `src/main.py`.

!!! note "Some examples take a `--mock` flag"
    A few examples (`langchain-research-agent`, `crewai-research-crew`) accept a `--mock`
    flag that replays a scripted, fully offline trajectory:

    ```bash
    uv run python src/main.py --mock
    ```

    These examples also **auto-fall back to mock mode** whenever `OPENAI_API_KEY` is unset,
    so `--mock` is mostly an explicit, CI-friendly way to force offline behavior. The
    per-example pages call out which examples support it. The remaining examples are offline
    by construction and need no flag.

To run an example's tests:

```bash
uv run pytest tests/ -v
```

## Mock mode vs. real-provider mode

| Mode | Gateway | LLM provider | How to run |
|---|---|---|---|
| **Mock / offline** (default) | none — policy is simulated locally | none — tools return mock data or a `--mock` trajectory replays | `uv run python src/main.py` (add `--mock` where supported) |
| **Real provider / production** | a running gateway (or SaaS workspace) enforces policy server-side | a real LLM key (e.g. `OPENAI_API_KEY`) drives tool selection | set the gateway + provider env vars, drop `mode="sdk-only"`, swap the local policy engine for the gateway-backed interceptor |

In **mock mode**, each example ships a `LocalPolicyEngine` (or example-specific variant such
as `BalancedPolicyEngine` / `CrewPolicyEngine`) that mirrors the gateway wire format locally.
This is what lets the demos run governance logic — allow / deny / pending — without contacting
a gateway.

In **production mode**, you start a gateway and the SDK enforces the policy configured there
automatically. Each per-example page's *Prerequisites & running it* section shows the exact
production command.

## Gateway and environment variables

### What the examples read

The examples read their gateway connection from these environment variables (resolved inside
each example's `src/main.py`):

| Variable | Purpose | Default in the examples |
|---|---|---|
| `AGENT_ASSEMBLY_GATEWAY_URL` | Base URL of the governance gateway | `http://localhost:8080` |
| `AGENT_ASSEMBLY_API_KEY` | API key sent to the gateway | unset (offline) |
| `OPENAI_API_KEY` | Optional LLM provider key for real-provider mode | unset (mock) |

Each example ships a `.env.example` you can copy to `.env` and fill in for production mode:

```bash
cp .env.example .env
# edit .env, then run with the variables exported, e.g.:
AGENT_ASSEMBLY_GATEWAY_URL=http://localhost:8080 \
AGENT_ASSEMBLY_API_KEY=your-key \
uv run python src/main.py
```

!!! note "Example env vars vs. the SDK's own resolver"
    The examples pass `gateway_url` / `api_key` **explicitly** to `init_assembly()`, reading
    them from the `AGENT_ASSEMBLY_*` variables shown above and defaulting to
    `http://localhost:8080`. The SDK *itself* has a separate built-in resolver chain that,
    when you **omit** those arguments, reads `AASM_GATEWAY_URL` / `AASM_API_KEY`, then
    `~/.aasm/config.yaml`, then probes a local gateway on `http://localhost:7391`. See
    [Configuration](../configuration.md#resolution-order) for that resolver. The examples use
    explicit arguments, so they use the `AGENT_ASSEMBLY_*` names and the `:8080` default —
    follow each example's README for its exact commands.

## Next steps

- Start with [LangChain — basic agent](langchain-basic-agent.md) for the simplest end-to-end
  governed agent.
- See the [Examples overview](index.md) for the full list and which governance control each
  one demonstrates.
- For the universal `init_assembly()` pattern and adapter detection, see
  [Framework support](framework-support.md).
