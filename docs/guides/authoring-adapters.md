# Authoring a framework adapter

A **framework adapter** teaches the Agent Assembly SDK how to govern a third-party AI
framework (LangChain, CrewAI, OpenAI Agents, …) *without* that framework being aware of
Agent Assembly. This guide walks you from zero to a published, installable adapter package.

Every adapter implements one ABC — [`FrameworkAdapter`][src-base] — and is discovered either
by being registered in-tree or by advertising a Python **entry point**. The companion
reference implementation is [`examples/adapters/template_adapter.py`][template]: a minimal,
runnable adapter you can copy and adapt.

[src-base]: https://github.com/ai-agent-assembly/python-sdk/blob/master/agent_assembly/adapters/base.py
[template]: https://github.com/ai-agent-assembly/python-sdk/blob/master/examples/adapters/template_adapter.py

---

## 1. Prerequisites

- **Python 3.10+** (the SDK targets 3.12 in CI; the public API is 3.10-compatible).
- A working understanding of your **target framework's hook/callback system** — the
  method, callback, or class you can wrap to observe and gate tool/agent execution.
  Adapters work by intercepting that point, so you need to know *where* in the framework
  a tool call happens before you can govern it.
- The SDK installed in a virtualenv:

    ```bash
    uv sync
    ```

---

## 2. Quickstart: copy the reference template

The fastest start is to copy the runnable template adapter and run it:

```bash
cp examples/adapters/template_adapter.py my_adapter.py
uv run python my_adapter.py          # runs the lifecycle demo offline
uv run aasm adapter validate my_adapter.py   # checks the contract — expect 7/7 PASS
```

The template governs a self-contained fictional framework so it runs with no third-party
dependencies and no reachable gateway. Replace the fictional `ExampleFramework` and the
monkey-patch in `register_hooks` with your real framework's classes, then re-run the two
commands above.

---

## 3. The `FrameworkAdapter` interface

`FrameworkAdapter` is an `ABC` with **four required (abstract) methods**. The base class also
provides several concrete helpers (`register`, `validate_registration`, `is_available`,
`get_active_version`, `set_process_agent_id`) that you normally do **not** override.

| Method | Signature | What you must do |
| --- | --- | --- |
| `get_framework_name` | `() -> str` | Return the **canonical importable package name** (e.g. `"crewai"`). Must be non-empty. The registry uses it to check availability via `importlib.import_module`. |
| `get_supported_versions` | `() -> list[str]` | Return a **non-empty list** of non-empty PEP 440 version-range strings (e.g. `[">=0.1.0"]`). |
| `register_hooks` | `(interceptor: GovernanceInterceptor) -> None` | Install your framework-specific monkey-patches, routing intercepted calls through `interceptor`. |
| `unregister_hooks` | `() -> None` | Tear down every patch installed by `register_hooks`. **Must be idempotent** — calling it twice must not raise. |

### Implementation notes

- **`get_framework_name`** — must match the framework's import name so `is_available()`
  (which the registry calls before activating you) returns `True` only when the framework is
  actually installed. Empty/whitespace names raise `AdapterValidationError` during
  `register()`.
- **`get_supported_versions`** — an empty list, or any empty range string, raises
  `AdapterValidationError`. These ranges document compatibility; the base class validates
  their *shape*, not the running framework version.
- **`register_hooks`** — receives the live `interceptor`. Do the actual monkey-patching here
  (see [§5 Hook patterns](#5-hook-patterns)). Built-in adapters delegate to one or more
  internal *patch* objects exposing `apply()` / `revert()`; see ADR-0001 in
  [Development → ADR-0001](../development/adr/0001-hook-architecture.md). Lazily import the
  framework inside this method so importing your adapter never hard-fails when the framework
  is absent.
- **`unregister_hooks`** — must revert patches (ideally in reverse install order) and be
  safe to call when no hooks are active. Guard with a "patched" flag so a double-call is a
  no-op. The validator enforces this by calling it twice.

Do **not** call `register_hooks` directly — call `adapter.register(interceptor)`, which runs
`validate_registration()` first so contract errors surface *before* any hook is attached.

A complete, working version of all four methods is in the
[template adapter][template]; here is the shape:

```python
from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor


class MyFrameworkAdapter(FrameworkAdapter):
    def get_framework_name(self) -> str:
        return "my_framework"

    def get_supported_versions(self) -> list[str]:
        return [">=1.0.0,<2.0.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        # Install monkey-patches that route framework calls through interceptor.
        ...

    def unregister_hooks(self) -> None:
        # Revert all patches installed by register_hooks(); must be idempotent.
        ...
```

---

## 4. The `GovernanceInterceptor` contract and the events you emit

[`GovernanceInterceptor`][src-base] is a **structural** `typing.Protocol` with **no required
methods**. It is a duck-typed marker: any object can be an interceptor. Adapters therefore
call interceptor methods **defensively** — look the method up with `getattr` and only call it
when it exists:

```python
check = getattr(interceptor, "check_tool_call", None)
if callable(check):
    decision = check(tool_name=tool_name, args=args)
```

This keeps an adapter working against both the full governance interceptor wired by
`init_assembly()` and a minimal stub used in tests.

### Conventional interceptor methods

Because the Protocol is open, there is **no fixed enum of event types**. The built-in
adapters use the following method-name conventions; mirror the ones that fit your framework's
execution model. Each returns either nothing (a pure notification) or a **decision** — a
status string `"allow" | "deny" | "pending"`, or a mapping `{"status": ..., "reason": ...}`.

| Convention method | Direction | Purpose |
| --- | --- | --- |
| `check_tool_start` / `check_tool_call` | adapter → interceptor, returns decision | Pre-execution gate for a tool call; `deny` blocks it. |
| `wait_for_tool_approval` | adapter → interceptor, returns decision | Block until a `pending` tool call is approved or rejected (human-in-the-loop). |
| `get_pending_tool_approval_timeout_seconds` | adapter → interceptor | Configurable timeout for the approval wait. |
| `record_result` / `on_tool_end` | adapter → interceptor, no return | Offer a governed tool call's outcome for audit. Over a connected runtime the SDK's interceptor resolves both names and writes the record to the runtime's event channel — a handoff, not a retention guarantee; without one neither resolves and the `getattr` guard finds nothing. **Your adapter must call this on the denied path too**, passing `denied=True` so the record is distinguishable from a tool that ran and returned the denial text. `_shared.audit_record.record_denied_tool_result` (and its `a`-prefixed async sibling) is what the eleven governing adapters call there; it suppresses a raising hook, because a decided deny is final regardless of audit outcome (AAASM-5787). |
| `record` | adapter → interceptor, no return | Generic structured event (e.g. `action="task_start"`). **No interceptor this SDK ships resolves this name** — unlike the row above, `record` was not wired by AAASM-5750. The CrewAI patch looks it up for task start/complete (`crewai/patch.py:429,445`) and finds nothing, so those events are recorded only by a caller-supplied handler. |

!!! note "These are conventions, not a typed contract"
    The names above are what today's built-in adapters happen to call (see the CrewAI patch
    in `agent_assembly/adapters/crewai/patch.py`). Always `getattr`-guard them. A future
    release may formalise this into typed methods on the Protocol.

A **pending → approval** flow looks like:

```python
decision = check_tool_start(...)          # may return {"status": "pending"}
if status == "pending":
    decision = wait_for_tool_approval(...) # blocks until resolved or times out
# now decision is "allow" or "deny"
```

---

## 5. Hook patterns

There are three ways to wire an adapter into a framework. Pick the one your framework
supports best.

### Callback-based

Register a callback/handler object with the framework's own callback system (LangChain's
`BaseCallbackHandler` is the canonical example; the `LangChainAdapter` builds one in
`register_hooks` and exposes it via `get_callback_handler()`).

- **Pros:** first-class, framework-sanctioned, survives framework internal refactors, no
  reliance on private attributes.
- **Cons:** only available if the framework *has* a callback system, and only sees the events
  that system emits — anything outside it is invisible.

### Wrapper-based

Wrap a public method on a framework class with `functools.wraps`, run your governance logic,
then delegate to the original. This is what the [template adapter][template] does, and what
the CrewAI adapter does to `BaseTool.run` / `Task.execute_sync`.

- **Pros:** works on any framework with a public entry point; you control exactly when the
  check runs relative to the real call; clean revert by restoring the saved original.
- **Cons:** couples you to the wrapped method's signature; if the framework changes that
  method you must follow.

### Monkey-patch-based

Replace a function or attribute outright (a degenerate case of wrapping where you may target
module-level functions or private internals).

- **Pros:** can reach things with no public hook at all.
- **Cons:** most brittle; most likely to break on framework upgrades; easiest to leave the
  process in a bad state if revert is incomplete. Use only as a last resort, and always store
  the original + a "patched" flag so `unregister_hooks` is exact and idempotent.

Whichever you choose, `unregister_hooks` must fully undo it. The template's
`_PATCHED_FLAG` / `_ORIGINAL_RUN_TOOL` sentinel pattern is the recommended approach.

---

## 6. Testing your adapter

!!! warning "There is no `AdapterTestHarness` fixture in the SDK today"
    Earlier planning referenced an `AdapterTestHarness` pytest fixture. It does **not** exist
    in the current codebase. Test your adapter with the two real mechanisms below; if a
    shared harness is added later this section will be updated.

### Contract validation (the in-tree validator)

The SDK ships a contract validator, exposed both as a CLI command and as a Python function.
Run it against your adapter file or dotted module:

```bash
uv run aasm adapter validate path/to/my_adapter.py
# or:  uv run aasm adapter validate my_package.my_adapter
```

It runs seven checks — inheritance, all four abstract methods implemented, non-empty
framework name, non-empty version ranges, `register_hooks` signature, `unregister_hooks`
idempotency, and entry-point metadata (when a `pyproject.toml` is present). The reference
template passes all seven:

```text
Results: 7 passed, 0 failed, 7 total
```

You can also call it programmatically in a unit test:

```python
from agent_assembly.cli.adapter_validator import validate_adapter
from my_package.my_adapter import MyFrameworkAdapter


def test_adapter_passes_contract() -> None:
    results = validate_adapter(MyFrameworkAdapter, "my_package/my_adapter.py")
    assert all(r.passed for r in results), [r.message for r in results if not r.passed]
```

### Lifecycle unit tests with a stub interceptor

Drive `register_hooks` / `unregister_hooks` with a tiny recording interceptor and a mocked
(or fictional) framework class, then assert that an allowed call passes through, a denied call
is blocked, and teardown restores the original. The template adapter's `__main__` demo is a
runnable model of exactly this flow.

```python
class RecordingInterceptor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def check_tool_call(self, *, tool_name: str, args: dict) -> dict:
        self.calls.append(tool_name)
        return {"status": "deny" if tool_name == "shell" else "allow", "reason": None}


def test_denies_shell() -> None:
    from examples.adapters.template_adapter import ExampleFramework, TemplateAdapter

    adapter, interceptor, fw = TemplateAdapter(), RecordingInterceptor(), ExampleFramework()
    adapter.register_hooks(interceptor)
    try:
        assert fw.run_tool("shell", cmd="rm -rf /").startswith("[BLOCKED")
        assert "shell" in interceptor.calls
    finally:
        adapter.unregister_hooks()
        adapter.unregister_hooks()  # idempotent
```

Place real adapter tests under `test/unit/adapters/<framework_name>/` (lifecycle, with the
framework mocked) and `test/integration/adapters/<framework_name>/` (a minimal end-to-end flow
with the real framework imported), as described in
[CONTRIBUTING.md](https://github.com/ai-agent-assembly/python-sdk/blob/master/CONTRIBUTING.md#adding-a-new-framework-adapter).

---

## 7. Publishing: entry points and naming

A community adapter ships as its own pip-installable package and is discovered at runtime via
a Python **entry point** in the `agent_assembly.adapters` group. `AdapterRegistry` loads every
entry point in that group, verifies the loaded object is a `FrameworkAdapter` subclass, and
registers it — so `init_assembly()` activates it automatically when the framework is present.

### Naming convention

Name the distribution **`aa-adapter-<framework>`** (e.g. `aa-adapter-myframework`). The
import package can be whatever you like, but the framework name returned by
`get_framework_name()` must equal the framework's import name.

### `pyproject.toml` entry-point config

```toml
[project]
name = "aa-adapter-myframework"
version = "0.1.0"
dependencies = ["agent-assembly", "myframework>=1.0.0"]

[project.entry-points."agent_assembly.adapters"]
myframework = "aa_adapter_myframework.adapter:MyFrameworkAdapter"
```

The entry-point **value** is `module.path:ClassName`. The `aasm adapter validate`
`entry_point_metadata` check confirms this points at your adapter class when it finds a
`pyproject.toml` alongside the adapter.

### Verify discovery end to end

```bash
pip install -e .                              # install your adapter package
uv run aasm adapter validate aa_adapter_myframework.adapter   # 7/7 PASS, incl. entry point
python -c "from agent_assembly.adapters.registry import AdapterRegistry; \
print([a.get_framework_name() for a in AdapterRegistry().get_available_adapters_by_priority()])"
```

`get_available_adapters_by_priority()` triggers entry-point discovery; your framework name
appears in the list once the framework is importable.

---

## 8. PR checklist

When contributing a built-in adapter back to this repo (community packages live in their own
repos but should still meet this bar), confirm:

- [ ] Adapter subclasses `FrameworkAdapter` and implements all four abstract methods.
- [ ] `uv run aasm adapter validate <path-or-module>` reports **7 passed, 0 failed**.
- [ ] `unregister_hooks` is idempotent and fully reverts every patch.
- [ ] Framework is imported **lazily** (inside `register_hooks` / availability helpers), so
      importing the adapter never fails when the framework is absent.
- [ ] Unit tests under `test/unit/adapters/<framework_name>/` cover the patch install/revert
      lifecycle (framework mocked).
- [ ] Integration test under `test/integration/adapters/<framework_name>/` exercises a minimal
      real flow.
- [ ] `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy agent_assembly`
      are clean.
- [ ] Entry point declared in `pyproject.toml` under
      `[project.entry-points."agent_assembly.adapters"]` (for standalone packages).
- [ ] Distribution named `aa-adapter-<framework>`; `get_framework_name()` matches the
      framework's import name.
- [ ] Follows the repo
      [PR checklist](https://github.com/ai-agent-assembly/python-sdk/blob/master/CONTRIBUTING.md#pull-request-checklist).
