"""Wrap any tool function so the agent can only call it through the guardrails."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .approvals import Approvals
from .audit import AuditLog
from .killswitch import KillSwitch
from .ledger import SpendLedger


class Risk(Enum):
    READ = "read"            # internal, reversible: runs freely
    SPEND = "spend"          # costs money: needs budget
    EXTERNAL = "external"    # leaves the building (send, post, buy): needs exact approval and budget


@dataclass
class GuardedTool:
    name: str
    fn: Callable[..., tuple[object, float]]   # returns (result, actual_cost)
    risk: Risk
    worst_case_cost: float
    ledger: SpendLedger
    approvals: Approvals
    audit: AuditLog
    kill: KillSwitch

    def __call__(self, target: str, **payload):
        self.kill.guard()
        approver = None
        if self.risk is Risk.EXTERNAL:
            approver, reason = self.approvals.consume(self.name, target, payload)
            self.audit.write("approved", tool=self.name, target=target, approver=approver, reason=reason)
        rid = None
        if self.risk in (Risk.SPEND, Risk.EXTERNAL) and self.worst_case_cost > 0:
            rid = self.ledger.reserve(self.worst_case_cost, f"{self.name}->{target}")
            self.ledger.mark_sent(rid)
        try:
            result, cost = self.fn(target, **payload)
        except Exception as exc:
            # Sent but failed: cost unknown, stays reserved at worst case; never auto-retried.
            self.audit.write("failed_unknown_cost", tool=self.name, target=target, error=str(exc)[:200], reservation=rid)
            raise
        if rid:
            self.ledger.settle(rid, cost)
        self.audit.write("done", tool=self.name, target=target, cost=cost, approver=approver)
        self.kill.record(spend=cost, calls=1)
        return result
