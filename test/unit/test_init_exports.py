from __future__ import annotations

import importlib
import sys
import types


def test_all_includes_native_core_symbols_when_extension_is_available() -> None:
    fake_core = types.ModuleType("agent_assembly._core")

    class RuntimeClient: ...

    class GovernanceEvent: ...

    # Attrs do not exist on the ModuleType stub; this fake mimics the native
    # extension exporting these symbols.
    fake_core.RuntimeClient = RuntimeClient  # type: ignore[attr-defined]  # attr not on the static stub; set/used dynamically
    fake_core.GovernanceEvent = GovernanceEvent  # type: ignore[attr-defined]  # attr not on the static stub; set/used dynamically

    original_package = sys.modules.pop("agent_assembly", None)
    original_core = sys.modules.get("agent_assembly._core")

    try:
        sys.modules["agent_assembly._core"] = fake_core
        module = importlib.import_module("agent_assembly")

        assert "RuntimeClient" in module.__all__
        assert "GovernanceEvent" in module.__all__
        assert "PolicyResult" not in module.__all__
        assert "PolicyTimeoutError" not in module.__all__
    finally:
        sys.modules.pop("agent_assembly", None)
        if original_package is not None:
            sys.modules["agent_assembly"] = original_package

        if original_core is None:
            sys.modules.pop("agent_assembly._core", None)
        else:
            sys.modules["agent_assembly._core"] = original_core
