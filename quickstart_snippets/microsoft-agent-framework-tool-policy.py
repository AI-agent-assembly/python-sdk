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
