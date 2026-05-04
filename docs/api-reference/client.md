# Client

`agent_assembly.client.GatewayClient` is the HTTP client that talks to the governance gateway. It is created by [`init_assembly()`](index.md) and exposed as `AssemblyContext.client` for cases where user code needs to issue ad-hoc gateway calls outside the framework adapter path.

## `agent_assembly.client.GatewayClient`

::: agent_assembly.client.GatewayClient
    options:
      show_root_heading: true
      show_source: true
      show_signature_annotations: true
      separate_signature: true
      members_order: source
      filters:
        - "!^_"
