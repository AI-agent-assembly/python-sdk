# Exceptions

The SDK raises a small, focused exception hierarchy rooted at `AssemblyError`. Every error you can catch from `agent_assembly` is a subclass of `AssemblyError` — code that does `except AssemblyError:` will catch any SDK-raised error without needing to enumerate the leaf classes.

## Hierarchy at a glance

```
AssemblyError                       (base)
├── AgentError                      (agent registration / lifecycle)
├── PolicyError                     (policy evaluation problems)
│   └── PolicyViolationError        (policy denied an action)
├── GatewayError                    (network / HTTP transport)
├── ConfigurationError              (bad init_assembly() arguments)
├── AdapterValidationError          (adapter ABC contract failure)
├── ToolExecutionBlockedError       (tool call blocked by policy)
└── MCPToolBlockedError             (MCP tool call blocked by policy)
```

## `agent_assembly.exceptions`

::: agent_assembly.exceptions
    options:
      show_root_heading: false
      show_root_toc_entry: false
      members_order: source
      show_bases: true
      show_source: true
      filters:
        - "!^_"
