"""Reference template adapter for the Agent Assembly Python SDK.

This module is a **minimal, runnable** ``FrameworkAdapter`` implementation that you
can copy as the starting point for a real community adapter (e.g. ``aa-adapter-<framework>``).

It governs a tiny *fictional* in-process framework defined at the bottom of this file
(``ExampleFramework``) so the whole thing runs offline with no third-party
dependencies and no reachable gateway. Replace ``ExampleFramework`` and the
monkey-patch logic in ``TemplateAdapter`` with your real framework's classes.

What this template demonstrates:

* The four required abstract methods of ``FrameworkAdapter``
  (``get_framework_name``, ``get_supported_versions``, ``register_hooks``,
  ``unregister_hooks``).
* A **wrapper-based monkey-patch**: ``register_hooks`` wraps the framework's
  tool-execution method so every call is routed through the governance
  interceptor *before* the original runs, enforcing an allow/deny decision.
* **Idempotent teardown**: ``unregister_hooks`` restores the original method and
  is safe to call more than once (the in-tree validator enforces this).

The ``GovernanceInterceptor`` contract is **structural** (a duck-typed
``typing.Protocol`` with no required methods). Adapters call whatever methods
the active interceptor exposes, guarding each call with ``getattr(...)`` so the
adapter degrades gracefully when a method is absent. This template uses a single
convention method, ``check_tool_call``, returning a decision mapping
``{"status": "allow" | "deny", "reason": str | None}``.

Run it directly to see the full lifecycle::

    uv run python examples/adapters/template_adapter.py
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor

# Sentinel attribute names stored on the patched class so we can detect a
# double-apply and find the original method during revert. Namespacing the
# attributes avoids collisions with the framework's own attributes.
_PATCHED_FLAG = "_aa_template_patched"
_ORIGINAL_RUN_TOOL = "_aa_template_original_run_tool"


def _format_blocked_message(reason: str | None) -> str:
    """Build the string returned to the agent when a tool call is denied.

    Returning a message (instead of raising) lets the agent observe the denial
    and choose a different action, which is the behaviour every built-in adapter
    follows.
    """
    reason_text = reason or "No reason provided."
    return f"[BLOCKED by governance policy] {reason_text}"


def _normalize_decision(decision: object) -> tuple[str, str | None]:
    """Normalize an interceptor's return value into ``(status, reason)``.

    Interceptors may return a bare status string or a mapping; anything we do
    not recognise is treated as ``allow`` so a misbehaving interceptor fails
    open *for this template*. A production adapter governing sensitive actions
    may prefer to fail closed (deny on unknown) — pick the posture that matches
    your threat model.
    """
    if isinstance(decision, str):
        return ("deny" if decision.strip().lower() == "deny" else "allow", None)
    if isinstance(decision, dict):
        status = str(decision.get("status", "allow")).strip().lower()
        reason = decision.get("reason")
        return ("deny" if status == "deny" else "allow", str(reason) if reason is not None else None)
    return ("allow", None)


class TemplateAdapter(FrameworkAdapter):
    """Reference adapter that governs the fictional ``ExampleFramework``.

    Copy this class, rename it ``<Framework>Adapter``, and repoint
    ``get_framework_name`` / the monkey-patch at your real framework.
    """

    def __init__(self) -> None:
        # Hold onto the interceptor and a flag so teardown is idempotent. A real
        # adapter that installs several patches typically holds a list of patch
        # objects instead.
        self._interceptor: GovernanceInterceptor | None = None
        self._target_cls: type[Any] | None = None

    # --- Required abstract method 1 -------------------------------------------------
    def get_framework_name(self) -> str:
        """Return the canonical importable package name of the framework.

        Must be a non-empty string. For a real adapter this is the framework's
        import name (e.g. ``"langchain"``, ``"crewai"``) so the registry can
        check availability via ``importlib.import_module``.
        """
        return "example_framework"

    # --- Required abstract method 2 -------------------------------------------------
    def get_supported_versions(self) -> list[str]:
        """Return the semantic-version ranges this adapter supports.

        Must be a non-empty list of non-empty strings (PEP 440 specifiers).
        """
        return [">=1.0.0,<2.0.0"]

    # --- Required abstract method 3 -------------------------------------------------
    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        """Install the governance hooks (wrapper-based monkey-patch).

        Called by ``init_assembly()`` (via ``AdapterRegistry.auto_detect``) with
        the live governance interceptor. Here we wrap ``ExampleFramework.run_tool``
        so every tool call is checked before it executes.
        """
        target_cls = _load_example_framework_class()
        if target_cls is None:  # framework not importable — nothing to patch
            return
        if getattr(target_cls, _PATCHED_FLAG, False):  # already patched — stay idempotent
            return

        self._interceptor = interceptor
        self._target_cls = target_cls
        original_run_tool: Callable[..., Any] = target_cls.run_tool

        @wraps(original_run_tool)
        def patched_run_tool(framework_self: Any, tool_name: str, **kwargs: Any) -> Any:
            # Ask the interceptor for a decision *before* running the tool.
            # getattr-guard the call so a minimal interceptor (one without
            # check_tool_call) simply allows the action through.
            check = getattr(interceptor, "check_tool_call", None)
            if callable(check):
                status, reason = _normalize_decision(check(tool_name=tool_name, args=dict(kwargs)))
                if status == "deny":
                    return _format_blocked_message(reason)
            # Allowed: run the real tool, then optionally report the result.
            result = original_run_tool(framework_self, tool_name, **kwargs)
            record = getattr(interceptor, "record_result", None)
            if callable(record):
                record(tool_name=tool_name, result=result)
            return result

        # Stash the original and flip the patched flag so revert can undo this.
        setattr(target_cls, _ORIGINAL_RUN_TOOL, original_run_tool)
        target_cls.run_tool = patched_run_tool
        setattr(target_cls, _PATCHED_FLAG, True)

    # --- Required abstract method 4 -------------------------------------------------
    def unregister_hooks(self) -> None:
        """Revert every patch installed by ``register_hooks`` — idempotently.

        Must not raise when no hooks are active; the in-tree validator calls it
        twice in a row to enforce this.
        """
        target_cls = self._target_cls
        if target_cls is None or not getattr(target_cls, _PATCHED_FLAG, False):
            return
        original_run_tool = getattr(target_cls, _ORIGINAL_RUN_TOOL, None)
        if callable(original_run_tool):
            target_cls.run_tool = original_run_tool
        for attr in (_ORIGINAL_RUN_TOOL, _PATCHED_FLAG):
            if hasattr(target_cls, attr):
                delattr(target_cls, attr)
        self._interceptor = None
        self._target_cls = None


# ---------------------------------------------------------------------------------
# Fictional framework + demo interceptor (replace with your real framework).
# ---------------------------------------------------------------------------------
class ExampleFramework:
    """A stand-in for a real AI framework with one governable entry point."""

    def run_tool(self, tool_name: str, **kwargs: Any) -> str:
        """Pretend to execute a tool and return its output."""
        return f"ran '{tool_name}' with {kwargs}"


def _load_example_framework_class() -> type[Any] | None:
    """Return the framework class to patch, or ``None`` if unavailable.

    A real adapter imports the framework lazily here (e.g.
    ``importlib.import_module("crewai.tools").BaseTool``) so importing the
    adapter never hard-fails when the framework is not installed.
    """
    return ExampleFramework


class _DenyShellInterceptor:
    """Tiny demo interceptor: denies the ``shell`` tool, allows everything else.

    This is *not* part of the public API — it only exists to make ``__main__``
    self-contained. In production the real governance interceptor is supplied by
    ``init_assembly()``.
    """

    def check_tool_call(self, *, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        # A real interceptor would inspect ``args`` (tool inputs) too; this demo
        # only gates on the tool name.
        del args
        if tool_name == "shell":
            return {"status": "deny", "reason": "shell access is not permitted"}
        return {"status": "allow", "reason": None}

    def record_result(self, *, tool_name: str, result: object) -> None:
        print(f"  [interceptor] recorded result of '{tool_name}': {result!r}")


def main() -> None:
    """Demonstrate the full adapter lifecycle end to end, offline."""
    adapter = TemplateAdapter()
    interceptor = _DenyShellInterceptor()
    framework = ExampleFramework()

    print(f"framework name : {adapter.get_framework_name()}")
    print(f"supported vers : {adapter.get_supported_versions()}")

    # Validate the contract before wiring (same checks the CLI validator runs).
    adapter.validate_registration()

    # Install hooks, then exercise both an allowed and a denied tool call.
    adapter.register_hooks(interceptor)
    print("allowed call   :", framework.run_tool("search", query="agent governance"))
    print("denied  call   :", framework.run_tool("shell", cmd="rm -rf /"))

    # Tear down — and prove it is idempotent (second call must not raise).
    adapter.unregister_hooks()
    adapter.unregister_hooks()
    print("after teardown :", framework.run_tool("shell", cmd="rm -rf /"))


if __name__ == "__main__":
    main()
