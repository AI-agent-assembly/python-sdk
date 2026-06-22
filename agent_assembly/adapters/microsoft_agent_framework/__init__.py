"""Microsoft Agent Framework adapter package.

Governs tool/function execution for Microsoft's unified Agent Framework
(PyPI ``agent-framework``, importable module ``agent_framework``). The single
interception point is ``agent_framework.FunctionTool.invoke`` — the async method
through which every function tool (``@tool``-decorated callables and
``FunctionTool(...)`` instances) executes — so governance applies regardless of
whether the user wires any framework middleware.

See :mod:`agent_assembly.adapters.microsoft_agent_framework.patch` for the hook
mechanics and ADR-0001 for the broader hook architecture.
"""

from agent_assembly.adapters.microsoft_agent_framework.adapter import (
    MicrosoftAgentFrameworkAdapter,
)
from agent_assembly.adapters.microsoft_agent_framework.patch import (
    MicrosoftAgentFrameworkPatch,
)

__all__ = ["MicrosoftAgentFrameworkAdapter", "MicrosoftAgentFrameworkPatch"]
