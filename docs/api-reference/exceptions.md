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

`PolicyTimeoutError` is also raised by the optional native runtime client (`agent_assembly._core`) when a policy check exceeds its deadline; it is **not** a subclass of `AssemblyError` because it originates from the Rust FFI layer. Catch it explicitly if you opt into the native fast path.

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
