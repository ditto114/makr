"""매크로 데이터 구조 정의."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
import uuid


@dataclass
class MacroNode:
    """매크로 실행 단위 노드."""

    title: str
    kind: str  # "condition", "action", "loop"
    config: Dict[str, Any] = field(default_factory=dict)
    children: List["MacroNode"] = field(default_factory=list)
    identifier: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        """사전으로 직렬화."""
        return {
            "title": self.title,
            "kind": self.kind,
            "config": self.config,
            "children": [child.to_dict() for child in self.children],
            "identifier": self.identifier,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "MacroNode":
        """사전에서 역직렬화."""
        children_payload = payload.get("children", [])
        node = cls(
            title=payload.get("title", "Unnamed"),
            kind=payload["kind"],
            config=payload.get("config", {}),
            identifier=payload.get("identifier", str(uuid.uuid4())),
        )
        node.children = [cls.from_dict(child) for child in children_payload]
        return node


@dataclass
class Macro:
    """매크로 전체 구성을 나타내는 클래스."""

    name: str = "새 매크로"
    nodes: List[MacroNode] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "nodes": [node.to_dict() for node in self.nodes],
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Macro":
        macro = cls(name=payload.get("name", "불러온 매크로"))
        macro.nodes = [MacroNode.from_dict(node) for node in payload.get("nodes", [])]
        return macro

    def add_node(self, node: MacroNode, parent: MacroNode | None = None) -> None:
        """루트 또는 특정 부모 노드에 자식으로 추가."""
        if parent is None:
            self.nodes.append(node)
        else:
            parent.children.append(node)

    def remove_node(self, target: MacroNode) -> None:
        """노드를 트리에서 제거."""
        for nodes in (self.nodes,):
            if target in nodes:
                nodes.remove(target)
                return
        # 재귀 탐색
        for node in self.nodes:
            if self._remove_from_children(node, target):
                return

    def _remove_from_children(self, parent: MacroNode, target: MacroNode) -> bool:
        if target in parent.children:
            parent.children.remove(target)
            return True
        for child in parent.children:
            if self._remove_from_children(child, target):
                return True
        return False

    def find_by_identifier(self, identifier: str) -> MacroNode | None:
        """식별자로 노드 검색."""
        for node in self.nodes:
            found = self._find_recursive(node, identifier)
            if found:
                return found
        return None

    def _find_recursive(self, node: MacroNode, identifier: str) -> MacroNode | None:
        if node.identifier == identifier:
            return node
        for child in node.children:
            found = self._find_recursive(child, identifier)
            if found:
                return found
        return None
