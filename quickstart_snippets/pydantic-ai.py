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
