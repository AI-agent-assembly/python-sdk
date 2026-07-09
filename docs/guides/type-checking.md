# Type checking

The SDK is fully typed and ships its type information to consumers, so your own static type
checker (mypy, Pyright, …) understands the Agent Assembly API out of the box.

## PEP 561 — types are distributed

`agent_assembly` includes a [`py.typed`](https://peps.python.org/pep-0561/) marker, so type
checkers pick up the bundled annotations automatically once the package is installed — no
stub packages required. This is verified in CI by the **PEP 561 Type Distribution** workflow.

## Public type surface

Stable, importable types you can annotate against:

| Import | Kind | Notes |
| --- | --- | --- |
| `agent_assembly.types.AuditEvent` | `dataclass` | A governance event from the audit trail. |
| `agent_assembly.types.CallStackNode` | `dataclass` | One node in an event's hierarchical call stack. |
| `agent_assembly.types.CallStackNodeKind` | type alias | `Literal["llm", "tool", "result"]`. |
| `agent_assembly.models.AgentConfig` | `pydantic.BaseModel` | Agent registration config. |
| `agent_assembly.models.AgentState` | `pydantic.BaseModel` | Agent runtime state. |
| `agent_assembly.models.PolicyEvaluation` | `pydantic.BaseModel` | Policy decision result. |

Import data types from their defining submodule (`agent_assembly.types`,
`agent_assembly.models`) as shown — this is what the SDK's own code does and keeps strict
checkers (mypy `--strict`, which enables `no-implicit-reexport`) happy. `init_assembly` and the
exception hierarchy are imported from the top-level `agent_assembly` package. The exception
types (`AssemblyError` and subtypes) are fully typed too; catch the most specific subtype you
care about.

## Checking your own code

Use any PEP 561-aware checker. With mypy:

```bash
pip install --pre agent-assembly mypy
mypy your_app.py
```

The SDK's annotations flow into your project, so mis-using the API (wrong argument types,
unhandled `None`, etc.) is caught before runtime.

## Worked example

A runnable, mypy-clean example lives at
[`examples/type_checking/`](https://github.com/ai-agent-assembly/python-sdk/tree/master/examples/type_checking).
It annotates against the public types above and is checked with:

```bash
uv run mypy examples/type_checking/type_checking_example.py
uv run python examples/type_checking/type_checking_example.py
```

## Developing the SDK itself

Contributors run mypy over the package (config in `mypy.ini` / `pyproject.toml`):

```bash
uv run mypy agent_assembly
```

The adapter base class and registry are held to mypy strict. See
[CONTRIBUTING.md](https://github.com/ai-agent-assembly/python-sdk/blob/master/CONTRIBUTING.md)
for the full lint/type workflow.
