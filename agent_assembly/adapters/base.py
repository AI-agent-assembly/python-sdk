from __future__ import annotations

from abc import ABC, abstractmethod
import importlib
from typing import Protocol


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

    def is_available(self) -> bool:
        try:
            importlib.import_module(self.get_framework_name())
        except ImportError:
            return False

        return True

    def get_active_version(self) -> str | None:
        try:
            module = importlib.import_module(self.get_framework_name())
        except ImportError:
            return None

        version = getattr(module, "__version__", None)
        if isinstance(version, str):
            return version

        return None
