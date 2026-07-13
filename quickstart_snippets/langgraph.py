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
