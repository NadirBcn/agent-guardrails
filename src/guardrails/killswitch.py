"""Kill rules written before launch. Each rule looks at running metrics; the first that fires trips the switch and
every guarded tool refuses to act until a human resets it."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


class Tripped(RuntimeError):
    pass


@dataclass
class KillRule:
    name: str
    check: Callable[[dict], bool]
    explanation: str


@dataclass
class KillSwitch:
    rules: list[KillRule]
    tripped_by: str | None = None
    metrics: dict = field(default_factory=dict)

    def record(self, **values) -> None:
        for k, v in values.items():
            self.metrics[k] = self.metrics.get(k, 0) + v
        for rule in self.rules:
            if self.tripped_by is None and rule.check(self.metrics):
                self.tripped_by = f"{rule.name}: {rule.explanation}"

    def guard(self) -> None:
        if self.tripped_by:
            raise Tripped(self.tripped_by)

    def reset(self, who: str, reason: str) -> str:
        if len(reason.strip()) < 8:
            raise ValueError("reset needs a written reason")
        was, self.tripped_by = self.tripped_by, None
        return f"reset by {who}: {reason} (was: {was})"
