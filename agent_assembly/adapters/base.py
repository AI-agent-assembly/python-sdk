from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol


class GovernanceInterceptor(Protocol):
    pass


class FrameworkAdapter(ABC):
    @abstractmethod
    def get_framework_name(self) -> str:
        ...
