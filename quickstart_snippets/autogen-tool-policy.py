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
