"""Contract test for the AAASM-4014 ``__getattr__`` with the REAL LangChain base.

AAASM-4014 added a delegating ``__getattr__`` to ``AssemblyCallbackHandler`` that
forwards any attribute the class does not define to the wrapped governance
``_interceptor``. Its safety argument — that delegation never shadows or
synthesizes a genuine LangChain callback-contract member — could not be
CI-exercised because ``langchain_core`` was not a test dependency, so every other
delegation test runs against the empty ``_FallbackBaseCallbackHandler`` where the
contract members simply do not exist.

This module closes that gap. It is guarded by ``pytest.importorskip`` so the
default (langchain-free) suite skips it cleanly, and it only runs when the
``langchain-test`` dependency group is installed:

    uv sync --group langchain-test
    .venv/bin/python -m pytest \
        test/unit/adapters/langchain/test_getattr_contract_with_langchain.py

With ``langchain-core`` present the real
``langchain_core.callbacks.BaseCallbackHandler`` becomes the base of
``AssemblyCallbackHandler``, so this file asserts:

(a) every LangChain callback-contract member (the ``on_*`` event methods, the
    ``ignore_*`` flags, ``raise_error`` / ``run_inline``) resolves through normal
    class attribute lookup to the base class (or to the four methods
    ``AssemblyCallbackHandler`` overrides) and is NEVER produced by
    ``__getattr__`` delegation; and

(b) with langchain co-installed, a non-LangChain adapter path (crewai's
    ``check_tool_start`` lookup) still reaches the real interceptor and DENIES a
    policy-denied tool under ``enforce`` — i.e. delegation of genuinely-missing
    governance members is unaffected by the real base class populating dozens of
    contract members.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

# The whole module is meaningful only with the real LangChain base class present.
langchain_core = pytest.importorskip("langchain_core")
from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402

from agent_assembly.adapters.langchain import AssemblyCallbackHandler  # noqa: E402

# The LangChain callback contract: event-dispatch methods the CallbackManager
# resolves by name via ``getattr(handler, event_name)``. Four of these are
# overridden by AssemblyCallbackHandler; the rest are inherited from the real
# base-class mixins. None may be synthesized by ``__getattr__``.
_CONTRACT_EVENT_METHODS: tuple[str, ...] = (
    "on_llm_start",
    "on_chat_model_start",
    "on_llm_new_token",
    "on_llm_end",
    "on_llm_error",
    "on_chain_start",
    "on_chain_end",
    "on_chain_error",
    "on_tool_start",
    "on_tool_end",
    "on_tool_error",
    "on_text",
    "on_retry",
    "on_agent_action",
    "on_agent_finish",
    "on_retriever_start",
    "on_retriever_end",
    "on_retriever_error",
    "on_custom_event",
)

# The contract configuration flags the CallbackManager reads to decide whether to
# dispatch. Each is a real base-class property that must resolve without touching
# the interceptor.
_CONTRACT_FLAGS: tuple[str, ...] = (
    "ignore_llm",
    "ignore_retry",
    "ignore_chain",
    "ignore_agent",
    "ignore_retriever",
    "ignore_chat_model",
    "ignore_custom_event",
    "raise_error",
    "run_inline",
)

# Contract members AssemblyCallbackHandler defines itself; the remaining members
# must resolve to a ``langchain_core`` class. The four tool/llm methods carry the
# governance dispatch; ``raise_error`` is overridden to True so LangChain propagates
# a DENY instead of swallowing it (AAASM-4658).
_OVERRIDDEN_MEMBERS: frozenset[str] = frozenset(
    {"on_tool_start", "on_tool_end", "on_llm_start", "on_llm_end", "raise_error"}
)


class _ExplodingInterceptor:
    """Interceptor spy that records — and rejects — every delegated lookup.

    ``AssemblyCallbackHandler.__getattr__`` only fires when normal attribute
    lookup fails and forwards to ``getattr(self._interceptor, name)``. Recording
    each such access here lets a test prove ``__getattr__`` never fired for a
    contract member; raising ``AttributeError`` mimics a genuinely-absent
    governance attribute.
    """

    def __init__(self) -> None:
        self.accessed: list[str] = []

    def __getattr__(self, name: str) -> Any:
        self.accessed.append(name)
        raise AttributeError(name)


def _defining_class(name: str) -> type:
    mro: tuple[type, ...] = AssemblyCallbackHandler.__mro__
    for cls in mro:
        if name in cls.__dict__:
            return cls
    raise AssertionError(f"{name!r} is not defined anywhere in the MRO")


def test_real_langchain_base_class_is_active() -> None:
    """Precondition: with langchain installed the real base is wired in."""
    from agent_assembly.adapters.langchain import callback_handler

    assert callback_handler._CallbackHandlerBase is BaseCallbackHandler
    assert BaseCallbackHandler in AssemblyCallbackHandler.__mro__


def test_contract_members_resolve_statically_not_via_getattr() -> None:
    """Every contract member is a genuine class attribute, never synthesized.

    ``inspect.getattr_static`` resolves attributes WITHOUT invoking
    ``__getattr__``; that it succeeds for each contract member proves the member
    exists on the class hierarchy. The spy interceptor additionally records any
    delegated access, so an empty record proves ``__getattr__`` never fired for
    the whole contract surface (the event-dispatch resolution path).
    """
    spy = _ExplodingInterceptor()
    handler = AssemblyCallbackHandler(spy)

    for name in (*_CONTRACT_EVENT_METHODS, *_CONTRACT_FLAGS):
        # Resolves through normal lookup — raises if it is not a real attribute.
        static_value = inspect.getattr_static(handler, name)
        assert static_value is not None

        owner = _defining_class(name)
        if name in _OVERRIDDEN_MEMBERS:
            assert owner is AssemblyCallbackHandler
        else:
            assert owner.__module__.startswith(
                "langchain_core"
            ), f"{name!r} resolved to {owner!r}, not the LangChain base contract"

    # Live attribute access (bound methods + evaluated flag properties) also
    # resolves without ever delegating to the interceptor.
    for name in _CONTRACT_EVENT_METHODS:
        assert callable(getattr(handler, name))
    for name in _CONTRACT_FLAGS:
        # ``raise_error`` is intentionally True (AAASM-4658); the rest are False.
        expected = name == "raise_error"
        assert getattr(handler, name) is expected

    assert spy.accessed == [], f"__getattr__ delegated contract members it must not: {spy.accessed}"


def test_getattr_still_delegates_non_contract_governance_members() -> None:
    """Positive control: ``__getattr__`` IS wired, it just never shadows contract.

    A governance entry point (``check_tool_start``) is NOT a LangChain contract
    member, so it is absent from the class and static lookup fails — but live
    attribute access must route through ``__getattr__`` to the interceptor. This
    is the exact lookup a co-installed adapter performs.
    """
    spy = _ExplodingInterceptor()
    handler = AssemblyCallbackHandler(spy)

    with pytest.raises(AttributeError):
        inspect.getattr_static(handler, "check_tool_start")

    # Live lookup delegates; the spy raises AttributeError to mimic absence, but
    # only after recording that the delegation reached it.
    with pytest.raises(AttributeError):
        _ = handler.check_tool_start

    assert "check_tool_start" in spy.accessed


# --- (b) crewai adapter path reaches real governance with langchain co-installed ---


class _FakeRuntimeClient:
    """Native RuntimeClient stand-in returning a fixed decision."""

    def __init__(self, decision: str, reason: str = "") -> None:
        self._decision = decision
        self._reason = reason
        self.calls: list[tuple[str, str, str | None, str | None]] = []

    def query_policy(
        self,
        agent_id: str,
        action_type: str,
        tool_name: str | None = None,
        tool_args_json: str | None = None,
    ) -> dict[str, str]:
        self.calls.append((agent_id, action_type, tool_name, tool_args_json))
        return {"decision": self._decision, "reason": self._reason}


class _FakeGatewayClient:
    """GatewayClient stand-in with no ``check_tool_start`` (production shape)."""

    def __init__(self) -> None:
        self.agent_id = "agent-001"


def test_langchain_coinstall_denies_through_crewai_adapter() -> None:
    """Delegation still blocks a denied tool with the real base class present.

    The existing AAASM-4014 regression asserts this against the empty fallback
    base; here the real ``BaseCallbackHandler`` populates the handler with dozens
    of contract members. ``check_tool_start`` is not among them, so a crewai-style
    ``getattr(handler, "check_tool_start")`` must still delegate to the wrapped
    ``RuntimeQueryInterceptor`` and surface the runtime DENY under enforce.
    """
    from agent_assembly.adapters.crewai import patch as crewai_patch
    from agent_assembly.core.runtime_interceptor import RuntimeQueryInterceptor

    interceptor = RuntimeQueryInterceptor(
        _FakeGatewayClient(),
        _FakeRuntimeClient("deny", reason="blocked"),
        "agent-001",
        enforce=True,
    )
    callback_handler = AssemblyCallbackHandler(interceptor)

    # Enforce posture is detected through the wrapping handler even though the
    # real base class does not expose ``_enforce``.
    assert crewai_patch._interceptor_enforces(callback_handler) is True

    decision = crewai_patch._invoke_sync_tool_check(
        callback_handler,
        tool_name="web_search",
        tool_args={"q": "x"},
        agent_id="agent-001",
    )
    status, reason = crewai_patch._normalize_decision(decision, enforce=True)

    assert status == "deny"
    assert reason == "blocked"
