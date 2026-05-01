from __future__ import annotations

from abc import ABC, abstractmethod
import importlib
from typing import Protocol

from agent_assembly.exceptions import AdapterValidationError


class GovernanceInterceptor(Protocol):
    """Protocol implemented by governance interceptors used by adapters."""

    pass


class FrameworkAdapter(ABC):
    """Abstract contract implemented by every framework adapter.

    This is the **public adapter API** — the interface that SDK users and
    third-party plugin authors interact with.  Each concrete adapter represents
    one AI framework (e.g. LangChain, CrewAI) and knows how to install
    governance hooks for that framework.

    The two key lifecycle methods are:

    - ``register_hooks(interceptor)`` — install framework-specific
      monkey-patches that route intercepted calls through the governance
      interceptor.  Internally, each adapter delegates to one or more
      ``RuntimePatch`` instances whose ``apply()`` method performs the
      actual monkey-patching.

    - ``unregister_hooks()`` — tear down all patches installed by this
      adapter, delegating to each patch's ``revert()`` method.

    Adapters are discovered and activated by ``AdapterRegistry.auto_detect()``
    which is the single detection path used by ``init_assembly()``.

    Adapters should be registered through ``register()`` so contract
    validation errors are raised before framework hooks are attached.

    See Also:
        ``RuntimePatch`` in ``core/assembly.py`` — the internal
        monkey-patch protocol with ``apply()`` / ``revert()`` methods.
        ADR-0001 (``docs/adr/0001-hook-architecture.md``) for the full
        architecture rationale.
    """

    @abstractmethod
    def get_framework_name(self) -> str:
        """Return the canonical importable framework package name.

        Error conditions:
        - Empty or whitespace-only names trigger `AdapterValidationError`
          during `register()`.
        """

        ...

    @abstractmethod
    def get_supported_versions(self) -> list[str]:
        """Return supported semantic version ranges for the framework.

        Error conditions:
        - Empty lists or empty range strings trigger `AdapterValidationError`
          during `register()`.
        """

        ...

    @abstractmethod
    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        """Attach framework hooks to a governance interceptor instance.

        Error conditions:
        - Framework-specific hook wiring failures should raise adapter-specific
          exceptions for the caller to handle.
        """

        ...

    @abstractmethod
    def unregister_hooks(self) -> None:
        """Detach all framework hooks in an idempotent way.

        Error conditions:
        - This method should avoid raising when no hooks are currently active.
        """

        ...

    def validate_registration(self) -> None:
        """Validate adapter contract values before hook registration.

        Raises:
            AdapterValidationError: If the framework name or version ranges
                violate the base adapter contract.
        """
        framework_name = self.get_framework_name()
        if not framework_name.strip():
            raise AdapterValidationError(
                "Adapter contract invalid: framework name must be non-empty."
            )

        supported_versions = self.get_supported_versions()
        if not supported_versions:
            raise AdapterValidationError(
                "Adapter contract invalid: supported versions must not be empty."
            )

        for version_range in supported_versions:
            if not version_range.strip():
                raise AdapterValidationError(
                    "Adapter contract invalid: version ranges must be non-empty strings."
                )

    def register(self, interceptor: GovernanceInterceptor) -> None:
        """Validate contract values and then attach framework hooks.

        Raises:
            AdapterValidationError: If `validate_registration()` fails.
        """
        self.validate_registration()
        self.register_hooks(interceptor)

    def is_available(self) -> bool:
        """Return True when the framework package can be imported.

        Error conditions:
        - Import failures are handled internally and return `False`.
        """

        try:
            importlib.import_module(self.get_framework_name())
        except ImportError:
            return False

        return True

    def get_active_version(self) -> str | None:
        """Return framework `__version__` when present, otherwise `None`.

        Error conditions:
        - Import failures and missing/non-string `__version__` values return
          `None`.
        """

        try:
            module = importlib.import_module(self.get_framework_name())
        except ImportError:
            return None

        version = getattr(module, "__version__", None)
        if isinstance(version, str):
            return version

        return None
