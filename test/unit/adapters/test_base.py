import pytest

from agent_assembly.adapters import FrameworkAdapter


class IncompleteAdapter(FrameworkAdapter):
    def get_framework_name(self) -> str:
        return "math"


def test_framework_adapter_requires_all_abstract_methods() -> None:
    with pytest.raises(TypeError):
        IncompleteAdapter()
