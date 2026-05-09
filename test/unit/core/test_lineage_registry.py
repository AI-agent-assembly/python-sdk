from __future__ import annotations

from agent_assembly.core.lineage import LineageRegistry


class TestLineageRegistryRecord:
    def test_record_root_agent(self) -> None:
        reg = LineageRegistry()
        reg.record("root-1")
        assert len(reg) == 1

    def test_record_child_agent(self) -> None:
        reg = LineageRegistry()
        reg.record("parent-1")
        reg.record("child-1", parent_agent_id="parent-1")
        assert len(reg) == 2

    def test_record_overwrite(self) -> None:
        reg = LineageRegistry()
        reg.record("agent-1", parent_agent_id="parent-a")
        reg.record("agent-1", parent_agent_id="parent-b")
        assert reg.ancestors_of("agent-1") == ["parent-b"]


class TestLineageRegistryChildrenOf:
    def test_children_of_root(self) -> None:
        reg = LineageRegistry()
        reg.record("root")
        reg.record("child-a", parent_agent_id="root")
        reg.record("child-b", parent_agent_id="root")
        children = reg.children_of("root")
        assert sorted(children) == ["child-a", "child-b"]

    def test_children_of_unknown_parent(self) -> None:
        reg = LineageRegistry()
        assert reg.children_of("nonexistent") == []

    def test_children_of_leaf_agent(self) -> None:
        reg = LineageRegistry()
        reg.record("leaf", parent_agent_id="root")
        assert reg.children_of("leaf") == []

    def test_children_of_returns_only_direct_children(self) -> None:
        reg = LineageRegistry()
        reg.record("root")
        reg.record("child", parent_agent_id="root")
        reg.record("grandchild", parent_agent_id="child")
        assert reg.children_of("root") == ["child"]


class TestLineageRegistryAncestorsOf:
    def test_ancestors_of_root_is_empty(self) -> None:
        reg = LineageRegistry()
        reg.record("root")
        assert reg.ancestors_of("root") == []

    def test_ancestors_of_direct_child(self) -> None:
        reg = LineageRegistry()
        reg.record("root")
        reg.record("child", parent_agent_id="root")
        assert reg.ancestors_of("child") == ["root"]

    def test_ancestors_of_grandchild(self) -> None:
        reg = LineageRegistry()
        reg.record("root")
        reg.record("child", parent_agent_id="root")
        reg.record("grandchild", parent_agent_id="child")
        assert reg.ancestors_of("grandchild") == ["child", "root"]

    def test_ancestors_of_unknown_agent(self) -> None:
        reg = LineageRegistry()
        assert reg.ancestors_of("ghost") == []

    def test_ancestors_of_three_level_chain(self) -> None:
        reg = LineageRegistry()
        for aid, pid in [("a", None), ("b", "a"), ("c", "b"), ("d", "c")]:
            reg.record(aid, parent_agent_id=pid)
        assert reg.ancestors_of("d") == ["c", "b", "a"]


class TestLineageRegistryLen:
    def test_empty_registry(self) -> None:
        assert len(LineageRegistry()) == 0

    def test_len_after_records(self) -> None:
        reg = LineageRegistry()
        reg.record("a")
        reg.record("b", parent_agent_id="a")
        assert len(reg) == 2
