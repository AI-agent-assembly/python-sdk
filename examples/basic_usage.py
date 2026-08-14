"""
Basic usage example for the Agent Assembly Python SDK.

This example demonstrates how to initialize the SDK and use its basic features.
"""

from agent_assembly import init_assembly
from agent_assembly.models import AgentConfig

# Initialize the assembly with your agent configuration
assembly = init_assembly(
    gateway_url="https://gateway.agent-assembly.dev",
    api_key="your-api-key-here",
    agent_id="my-agent-001",
    mode="auto",
)

# Create an agent configuration
agent_config = AgentConfig(
    agent_id="my-agent-001",
    name="My AI Agent",
    description="A sample AI agent using Agent Assembly SDK",
    version="1.0.0",
)

print(f"Agent configured: {agent_config.name}")
print(f"Agent ID: {agent_config.agent_id}")
print(f"Version: {agent_config.version}")

# The assembly client can now be used to interact with the governance gateway
# For example:
# - Register the agent with the gateway
# - Check policy compliance before executing actions
#
# Note: governed outcomes are offered to an audit hook on the interceptor. Over a
# connected runtime the SDK's own interceptor resolves it and forwards the record;
# without one the hook does not resolve and nothing is logged (AAASM-5750).

# Don't forget to shutdown the runtime when done
assembly.shutdown()
