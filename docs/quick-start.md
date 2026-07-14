# Quick Start

Govern your first agent in about five minutes. By the end you'll have an agent — in whichever
framework you already use — whose tool calls pass through the Agent Assembly policy gate, and it
runs **offline** against a local policy, so you need no API keys and no network access to the
outside world.

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

=== "poetry"

    ```bash
    {{ aa.commands.install_poetry }}            # pure-Python SDK
    {{ aa.commands.install_poetry_runtime }} # SDK + bundled aasm runtime binary (platform wheel)
    ```

=== "conda"

    `{{ aa.python_sdk.package_name }}` is not published on conda-forge or the
    Anaconda default channel — create a conda environment, then install from
    PyPI with `pip` inside it:

    ```bash
    {{ aa.commands.install_conda }}
    {{ aa.commands.install_conda_pip }}
    ```

!!! note "`--pre` is required for now"
    Agent Assembly is currently published only as a pre-release on PyPI, and `pip`
    skips pre-releases unless you pass `--pre` (already included above). Drop the flag
    once a stable (non-pre-release) version is published.

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

!!! note "Local-mode transports: `:7391` REST + `:50051` gRPC"
    `aasm start --mode local` binds **two** loopback surfaces in one process: the REST/dashboard
    API on `http://localhost:7391` (what `gateway_url` points to, and what the SDK probes and
    auto-starts) **and** the gRPC `AgentLifecycleService` on `127.0.0.1:50051`, which is the
    endpoint the native SDK uses to **register** your agent. You don't configure `:50051`
    yourself — registration dials it automatically — so a no-argument `init_assembly()` both
    connects and shows the agent in the dashboard. `:8080` is **not** the local gateway port;
    ignore older docs or examples that point registration there.

## 3. Govern your first agent

Agent Assembly governs whichever agent framework you already use. Pick your framework below —
each tab is the **governance-wiring slice** (`init_assembly()` plus that framework's adapter
hookup) taken verbatim from that framework's runnable example in the
[examples repo](https://github.com/ai-agent-assembly/examples/tree/master/python). Copy the
full, runnable script — imports, tools, and the agent run — from the linked example; the slice
below is the part that wires in governance.

Every example runs **offline** in `mode="sdk-only"` against a local policy, so you can try it
with no API keys and no outbound network.

<!-- BEGIN GENERATED: quickstart-framework-tabs -->

=== "Agno"

    ```python
    with init_assembly(
        gateway_url=gateway_url,
        api_key=api_key,
        agent_id="agno-demo-agent",
        mode="sdk-only",
    ) as ctx:
        print(f"  Agent:    {ctx.client.agent_id}")
        print(f"  Gateway:  {ctx.client.gateway_url}")
        print(f"  Mode:     {ctx.network_mode} (offline demo)")
        print()

        policy = LocalPolicyEngine()

        print("Policy rules (local simulation of gateway policy):")
        print("  DENY   — execute_sql, run_shell_command  (arbitrary execution)")
        print("  ALLOW  — everything else")
        print()

        # In production init_assembly() auto-detects Agno and wires the live
        # runtime as the interceptor automatically. In this offline sdk-only demo
        # there is no live runtime, so init_assembly() installs a no-op hook; we
        # revert it and re-apply the hook wired to our local policy so the demo
        # shows real allow/deny decisions without a gateway. (The patch is
        # idempotent, so we must revert the no-op hook before installing ours.)
        AgnoPatch(policy).revert()
        patch = AgnoPatch(policy)
        assert patch.apply(), (
            "Agno governance hook did not install — is agno importable?"
        )
    ```

=== "AutoGen"

    ```python
    with init_assembly(
        gateway_url=gateway_url,
        api_key=api_key,
        agent_id="autogen-demo-agent",
        mode="sdk-only",
    ) as ctx:
        print(f"  Agent:    {ctx.client.agent_id}")
        print(f"  Gateway:  {ctx.client.gateway_url}")
        print(f"  Mode:     {ctx.network_mode} (offline demo)")
        print()

        policy = LocalPolicyEngine()
    ```

=== "CrewAI"

    ```python
    with init_assembly(
        gateway_url=gateway_url,
        api_key=api_key,
        agent_id="crewai-research-crew",
        mode="sdk-only",
    ) as ctx:
        print(f"  Agent:    {ctx.client.agent_id}")
        print(f"  Gateway:  {ctx.client.gateway_url}")
        print(f"  Mode:     {ctx.network_mode} ({mode_label})")
        print()

        print("Crew members:")
        for member in CREW:
            print(f"  • {member.name:<11} — {member.role}")
        print()

        print("Crew policy (local simulation of gateway policy):")
        print("  APPROVAL — any agent attempting a file write must be approved")
        print(f"  BUDGET   — ${DAILY_BUDGET_USD:.2f} / day, shared across all agents")
        print("  TRACK    — every call recorded with its delegation call stack")
        print()

        policy = CrewPolicyEngine(approver=MockApprover(auto_approve=False))
        handler = AssemblyCallbackHandler(interceptor=policy)
    ```

=== "Custom (no framework)"

    ```python
    with init_assembly(
        gateway_url=gateway_url,
        api_key=api_key,
        agent_id="custom-tool-demo-agent",
        mode="sdk-only",
    ) as ctx:
        print(f"  Agent:    {ctx.client.agent_id}")
        print(f"  Gateway:  {ctx.client.gateway_url}")
        print(f"  Mode:     {ctx.network_mode} (offline demo)")
        print()

        policy = LocalPolicyEngine()

        raw_fns = {
            "compute_sum": compute_sum,
            "fetch_stock_price": fetch_stock_price,
            "send_http_request": send_http_request,
            "write_to_disk": write_to_disk,
        }
        tools = {name: governed(name, fn, policy) for name, fn in raw_fns.items()}
    ```

=== "Google ADK"

    ```python
    # Govern the concrete demo tool class BEFORE init_assembly so the offline
    # LocalPolicyEngine stays wired as the interceptor (the patch is idempotent).
    govern_tool_class(DemoTool, LocalPolicyEngine())

    try:
        with init_assembly(
            gateway_url=gateway_url,
            api_key=api_key,
            agent_id="google-adk-demo-agent",
            mode="sdk-only",
        ) as ctx:
            print(f"  Agent:    {ctx.client.agent_id}")
            print(f"  Gateway:  {ctx.client.gateway_url}")
            print(f"  Mode:     {ctx.network_mode} (offline demo)")
            print()

            print("Policy rules (local simulation of gateway policy):")
            print("  DENY    — delete_records, write_file  (destructive operations)")
            print("  PENDING — send_email                  (requires human approval)")
            print("  ALLOW   — everything else")
            print()
    finally:
        ungovern_tool_class(DemoTool)
    ```

=== "Haystack"

    ```python
    with init_assembly(
        gateway_url=gateway_url,
        api_key=api_key,
        agent_id="haystack-demo-agent",
        mode="sdk-only",
    ) as ctx:
        print(f"  Agent:    {ctx.client.agent_id}")
        print(f"  Gateway:  {ctx.client.gateway_url}")
        print(f"  Mode:     {ctx.network_mode} (offline demo)")
        print()

        print("Policy rules (local simulation of gateway policy):")
        print("  DENY   — execute_sql, run_shell_command  (arbitrary execution)")
        print("  ALLOW  — everything else")
        print()

        # init_assembly() has already auto-detected Haystack and patched
        # Tool.invoke — but in offline sdk-only mode it wires a no-op interceptor
        # (there is no live gateway/runtime to answer policy). For this *offline*
        # demo we revert that and re-install the same native adapter against a
        # LocalPolicyEngine so a real allow/deny is visible without a gateway. In
        # production you would instead point init_assembly() at a gateway and let
        # its auto-detected adapter enforce real policy — no manual re-install.
        print("Installing the native Haystack adapter against the demo policy...")
        HaystackPatch(LocalPolicyEngine()).revert()  # drop the auto-applied no-op patch
        patch = HaystackPatch(LocalPolicyEngine())
        installed = patch.apply()
    ```

=== "LangChain"

    ```python
    with init_assembly(
        gateway_url=gateway_url,
        api_key=api_key,
        agent_id="langchain-demo-agent",
        mode="sdk-only",
    ) as ctx:
        print(f"  Agent:    {ctx.client.agent_id}")
        print(f"  Gateway:  {ctx.client.gateway_url}")
        print(f"  Mode:     {ctx.network_mode} (offline demo)")
        print()

        policy = LocalPolicyEngine()
        handler = AssemblyCallbackHandler(interceptor=policy)
    ```

=== "LangChain (Research Agent)"

    ```python
    with init_assembly(
        gateway_url=gateway_url,
        api_key=api_key,
        agent_id="langchain-research-agent",
        mode="sdk-only",
    ) as ctx:
        print(f"  Agent:    {ctx.client.agent_id}")
        print(f"  Gateway:  {ctx.client.gateway_url}")
        print(f"  Mode:     {ctx.network_mode} ({mode_label})")
        print()

        policy = BalancedPolicyEngine(daily_budget_usd=DAILY_BUDGET_USD)
        handler = AssemblyCallbackHandler(interceptor=policy)
    ```

=== "LangGraph"

    ```python
    with init_assembly(
        gateway_url=gateway_url,
        api_key=api_key,
        agent_id="langgraph-demo-agent",
        mode="sdk-only",
    ) as ctx:
        print(f"  Agent:    {ctx.client.agent_id}")
        print(f"  Gateway:  {ctx.client.gateway_url}")
        print(f"  Mode:     {ctx.network_mode} (offline demo)")
        print()

        policy = LocalPolicyEngine()
        handler = AssemblyCallbackHandler(interceptor=policy)

        # Install LangGraph node-level governance hooks. The adapter wraps the
        # compiled graph's nodes so tool calls inside each node are governed.
        adapter = LangGraphAdapter()
        adapter.set_process_agent_id(ctx.client.agent_id)
        adapter.register_hooks(handler)
    ```

=== "LlamaIndex"

    ```python
    with init_assembly(
        gateway_url=gateway_url,
        api_key=api_key,
        agent_id="llamaindex-demo-agent",
        mode="sdk-only",
    ) as ctx:
        print(f"  Agent:    {ctx.client.agent_id}")
        print(f"  Gateway:  {ctx.client.gateway_url}")
        print(f"  Mode:     {ctx.network_mode} (offline demo)")
        print()

        print("Policy rules (local simulation of gateway policy):")
        print("  DENY   — execute_sql, run_shell_command  (arbitrary execution)")
        print("  ALLOW  — everything else")
        print()

        # Register the native LlamaIndex adapter against the local policy engine.
        # This patches FunctionTool.call so every tool call below is governed
        # automatically — no per-tool wrapper needed.
        #
        # init_assembly() in sdk-only mode already auto-detected LlamaIndex and
        # patched FunctionTool.call against a no-op interceptor (there is no
        # gateway offline). Revert that first so this example's LocalPolicyEngine
        # is the live interceptor; in production init_assembly wires the adapter
        # to the gateway and this manual step is unnecessary.
        print("Registering the native LlamaIndex governance adapter...")
        LlamaIndexPatch(callback_handler=None).revert()
        adapter = LlamaIndexAdapter()
        adapter.register_hooks(LocalPolicyEngine())
    ```

=== "Microsoft Agent Framework"

    ```python
    policy = LocalPolicyEngine()

    # Live path: install the governance hooks BEFORE init_assembly. The adapter
    # patches `agent_framework.FunctionTool.invoke`; because the patch is
    # idempotent, registering first makes init_assembly's auto-detection a no-op
    # and keeps the offline `LocalPolicyEngine` wired as the interceptor (rather
    # than the no-op interceptor auto-detection would install).
    adapter: MicrosoftAgentFrameworkAdapter | None = None
    if not mock:
        adapter = MicrosoftAgentFrameworkAdapter()
        adapter.set_process_agent_id("microsoft-agent-framework-demo-agent")
        adapter.register_hooks(policy)

    try:
        with init_assembly(
            gateway_url=gateway_url,
            api_key=api_key,
            agent_id="microsoft-agent-framework-demo-agent",
            mode="sdk-only",
        ) as ctx:
            print(f"  Agent:    {ctx.client.agent_id}")
            print(f"  Gateway:  {ctx.client.gateway_url}")
            print(f"  Mode:     {ctx.network_mode} (offline demo)")
            print()

            print("Policy rules (local simulation of gateway policy):")
            print("  DENY    — delete_records, write_file  (destructive operations)")
            print("  PENDING — send_email                  (requires human approval)")
            print("  ALLOW   — everything else")
            print()
    finally:
        if adapter is not None:
            adapter.unregister_hooks()
    ```

=== "OpenAI Agents SDK"

    ```python
    with init_assembly(
        gateway_url=gateway_url,
        api_key=api_key,
        agent_id="openai-agents-demo",
        mode="sdk-only",
    ) as ctx:
        print(f"  Agent:    {ctx.client.agent_id}")
        print(f"  Gateway:  {ctx.client.gateway_url}")
        print(f"  Mode:     {ctx.network_mode} (offline demo)")
        print()

        policy = LocalPolicyEngine()
        handler = AssemblyCallbackHandler(interceptor=policy)
    ```

=== "Pydantic AI"

    ```python
    adapter = PydanticAIAdapter()
    adapter.set_process_agent_id("pydantic-ai-demo-agent")
    adapter.register_hooks(LocalPolicyEngine())

    try:
        with init_assembly(
            gateway_url=gateway_url,
            api_key=api_key,
            agent_id="pydantic-ai-demo-agent",
            mode="sdk-only",
        ) as ctx:
            print(f"  Agent:    {ctx.client.agent_id}")
            print(f"  Gateway:  {ctx.client.gateway_url}")
            print(f"  Mode:     {ctx.network_mode} (offline demo)")
            print()

            print("Policy rules (local simulation of gateway policy):")
            print("  DENY    — delete_records, write_file  (destructive operations)")
            print("  PENDING — send_email                  (requires human approval)")
            print("  ALLOW   — everything else")
            print()
    finally:
        adapter.unregister_hooks()
    ```

=== "Semantic Kernel"

    ```python
    with init_assembly(
        gateway_url=gateway_url,
        api_key=api_key,
        agent_id="semantic-kernel-demo-agent",
        mode="sdk-only",
    ) as ctx:
        print(f"  Agent:    {ctx.client.agent_id}")
        print(f"  Gateway:  {ctx.client.gateway_url}")
        print(f"  Mode:     {ctx.network_mode} (offline demo)")
        print()

        policy = LocalPolicyEngine()
        kernel = build_kernel()
    ```

=== "smolagents"

    ```python
    policy = LocalPolicyEngine()
    patch = SmolagentsPatch(policy)
    patch.apply()

    print(f"Initializing Agent Assembly (gateway: {gateway_url}, sdk-only mode)...")

    with init_assembly(
        gateway_url=gateway_url,
        api_key=api_key,
        agent_id="smolagents-demo-agent",
        mode="sdk-only",
    ) as ctx:
    ```

=== "Strands Agents"

    ```python
    with init_assembly(
        gateway_url=gateway_url,
        api_key=api_key,
        agent_id="strands-demo-agent",
        mode="sdk-only",
    ) as ctx:
        print(f"  Agent:    {ctx.client.agent_id}")
        print(f"  Gateway:  {ctx.client.gateway_url}")
        print(f"  Mode:     {ctx.network_mode} (offline demo)")
        print()

        policy = LocalPolicyEngine()
    ```

<!-- END GENERATED: quickstart-framework-tabs -->

## What just happened

1. **`init_assembly()` wired in governance.** It registered the agent with the gateway and
   auto-loaded the adapter for your framework — every tool call from this point on is routed
   through the policy gate.
2. **`mode="sdk-only"` kept it offline.** The in-process adapter enforces on tool calls with no
   network sidecar, so the example runs deterministically with no real LLM or gateway
   round-trip.
3. **Tool calls were governed.** The adapter intercepts the framework's tool-invocation path and
   asks the policy engine for an allow/deny verdict before the tool actually runs.
4. **The `with` block tore everything down on exit** — adapter hooks were unwound and the
   gateway connection closed, leaving the process exactly as it was before.

If a tool call raises a `ToolExecutionBlockedError`, that is not a bug — the policy denied the
call. That's the product working. See
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
