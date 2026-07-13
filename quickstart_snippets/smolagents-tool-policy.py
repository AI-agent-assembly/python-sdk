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
