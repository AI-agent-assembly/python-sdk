# Models

Pydantic data models for gateway payloads. Every gateway request and response that crosses the SDK ↔ gateway boundary is represented by one of these models — there are no untyped `dict[str, Any]` payloads in the public API.

## Models

| Model | Purpose |
|---|---|
| `AgentConfig` | Configuration sent to the gateway when an agent registers. |
| `AgentState` | Current state snapshot returned by the gateway for an agent. |
| `PolicyEvaluation` | Result of a single policy evaluation (allow / deny + reason + policy id). |

## `agent_assembly.models`

::: agent_assembly.models
    options:
      show_root_heading: false
      show_root_toc_entry: false
      members_order: source
      show_bases: true
      show_source: true
      show_signature_annotations: true
      filters:
        - "!^_"
