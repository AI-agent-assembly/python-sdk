from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol


class GovernanceInterceptor(Protocol):
    pass


class FrameworkAdapter(ABC):
    @abstractmethod
    def get_framework_name(self) -> str:
        ...

    @abstractmethod
    def get_supported_versions(self) -> list[str]:
        ...

    @abstractmethod
    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        ...
