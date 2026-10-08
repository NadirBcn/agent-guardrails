"""Exact-scope approvals.

An approval covers one action on one target with one payload, identified by a hash. It expires, and it is consumed on
first use. Approving "send this email to Ana" does not approve a different email, a different recipient, or the same
email twice.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field


class ApprovalRequired(PermissionError):
    def __init__(self, request: "Request"):
        super().__init__(f"approval required: {request.action} -> {request.target} [{request.digest}]")
        self.request = request


def digest(action: str, target: str, payload: dict) -> str:
    blob = json.dumps({"a": action, "t": target, "p": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


@dataclass
class Request:
    action: str
    target: str
    payload: dict
    digest: str


@dataclass
class Approvals:
    ttl_seconds: float = 3600
    granted: dict = field(default_factory=dict)   # digest -> (approver, reason, expires_at)
    pending: dict = field(default_factory=dict)   # digest -> Request
    clock: callable = time.time

    def request(self, action: str, target: str, payload: dict) -> Request:
        r = Request(action, target, payload, digest(action, target, payload))
        self.pending[r.digest] = r
        return r

    def grant(self, d: str, approver: str, reason: str) -> None:
        if d not in self.pending:
            raise KeyError(f"no pending request {d}")
        if len(reason.strip()) < 8:
            raise ValueError("approvals need a written reason")
        self.granted[d] = (approver, reason.strip(), self.clock() + self.ttl_seconds)
        del self.pending[d]

    def consume(self, action: str, target: str, payload: dict) -> tuple[str, str]:
        d = digest(action, target, payload)
        g = self.granted.pop(d, None)
        if g is None or g[2] < self.clock():
            raise ApprovalRequired(self.request(action, target, payload))
        return g[0], g[1]
