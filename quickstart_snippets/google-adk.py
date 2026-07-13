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
