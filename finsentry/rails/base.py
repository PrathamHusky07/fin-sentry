from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal


@dataclass
class RailDecision:
    outcome: Literal["pass", "block", "sanitize", "error"]
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


class Rail(ABC):
    name: ClassVar[str]
    layer: ClassVar[Literal["input", "retrieval", "output"]]

    @abstractmethod
    def check(self, content: str, context: dict[str, Any]) -> RailDecision:
        ...
