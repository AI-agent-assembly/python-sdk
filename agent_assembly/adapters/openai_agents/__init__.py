"""OpenAI Agents adapter package."""

from agent_assembly.adapters.openai_agents.adapter import OpenAIAgentsAdapter
from agent_assembly.adapters.openai_agents.patch import OpenAIAgentsPatch

__all__ = ["OpenAIAgentsAdapter", "OpenAIAgentsPatch"]
