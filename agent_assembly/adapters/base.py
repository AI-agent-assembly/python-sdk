from __future__ import annotations

from abc import ABC, abstractmethod
import importlib
from typing import Protocol

from agent_assembly.exceptions import AdapterValidationError


class GovernanceInterceptor(Protocol):
    """Protocol implemented by governance interceptors used by adapters."""

    pass


class FrameworkAdapter(ABC):
    """Abstract contract implemented by every framework adapter."""

    @abstractmethod
    def get_framework_name(self) -> str:
        """Return the canonical importable framework package name."""

        ...

    @abstractmethod
    def get_supported_versions(self) -> list[str]:
        """Return supported semantic version ranges for the framework."""

        ...

    @abstractmethod
    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        """Attach framework hooks to a governance interceptor instance."""

        ...

    @abstractmethod
    def unregister_hooks(self) -> None:
        """Detach all framework hooks in an idempotent way."""

        ...

    def validate_registration(self) -> None:
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
        self.validate_registration()
        self.register_hooks(interceptor)

    def is_available(self) -> bool:
        """Return True when the framework package can be imported."""

        try:
            importlib.import_module(self.get_framework_name())
        except ImportError:
            return False

        return True

    def get_active_version(self) -> str | None:
        """Return framework __version__ when present, otherwise None."""

        try:
            module = importlib.import_module(self.get_framework_name())
        except ImportError:
            return None

        version = getattr(module, "__version__", None)
        if isinstance(version, str):
            return version

        return None
