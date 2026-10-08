"""Reserve-then-settle spend ledger.

The worst case is booked *before* a paid call, then settled to the real cost after it. If the process dies between
the two, the reservation stays on the books, so a crash can never let spending escape the cap. A call that was sent but
whose cost is unknown is never retried automatically: it stays reserved at worst case until someone reconciles it.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class BudgetExceeded(RuntimeError):
    pass


class SpendLedger:
    def __init__(self, path: str | Path, cap: float, per_call_cap: float | None = None):
        self.path, self.cap, self.per_call_cap = Path(path), float(cap), per_call_cap
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._save({"entries": {}})

    @contextmanager
    def _locked(self):
        with open(self.path.with_suffix(".lock"), "a+") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def _load(self) -> dict:
        return json.loads(self.path.read_text())

    def _save(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        os.replace(tmp, self.path)

    def committed(self) -> float:
        """Settled costs plus open reservations at their worst case."""
        e = self._load()["entries"].values()
        return round(sum(x["actual"] if x["state"] == "settled" else x["reserved"] for x in e
                         if x["state"] in ("reserved", "settled", "sent_unknown")), 6)

    def reserve(self, amount: float, purpose: str) -> str:
        if self.per_call_cap is not None and amount > self.per_call_cap:
            raise BudgetExceeded(f"{purpose}: worst case {amount} exceeds per-call cap {self.per_call_cap}")
        with self._locked():
            data = self._load()
            used = sum(x["actual"] if x["state"] == "settled" else x["reserved"] for x in data["entries"].values()
                       if x["state"] in ("reserved", "settled", "sent_unknown"))
            if used + amount > self.cap + 1e-9:
                raise BudgetExceeded(f"{purpose}: {used:.2f} committed + {amount:.2f} would exceed cap {self.cap:.2f}")
            rid = uuid.uuid4().hex[:10]
            data["entries"][rid] = {"purpose": purpose, "reserved": amount, "actual": None, "state": "reserved",
                                    "at": time.time()}
            self._save(data)
        return rid

    def mark_sent(self, rid: str) -> None:
        """Call left the building; from here on, never retry blindly."""
        self._update(rid, state="sent_unknown")

    def settle(self, rid: str, actual: float) -> None:
        with self._locked():
            data = self._load()
            e = data["entries"][rid]
            if e["state"] not in ("reserved", "sent_unknown"):
                raise ValueError(f"{rid} already {e['state']}")
            e.update(actual=float(actual), state="settled")
            self._save(data)

    def release(self, rid: str) -> None:
        """Only for calls that provably never left (e.g. failed validation before sending)."""
        with self._locked():
            data = self._load()
            e = data["entries"][rid]
            if e["state"] != "reserved":
                raise ValueError(f"cannot release {rid}: state is {e['state']} (sent calls must be settled)")
            e["state"] = "released"
            self._save(data)

    def _update(self, rid: str, **kw) -> None:
        with self._locked():
            data = self._load()
            data["entries"][rid].update(kw)
            self._save(data)
