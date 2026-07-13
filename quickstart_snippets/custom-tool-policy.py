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
