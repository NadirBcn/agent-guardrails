"""Append-only, hash-chained audit log: every line includes the hash of the line before, so edits or deletions are
detectable with verify()."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def _last_hash(self) -> str:
        lines = self.path.read_text().splitlines()
        return json.loads(lines[-1])["hash"] if lines else "genesis"

    def write(self, event: str, **fields) -> dict:
        rec = {"at": round(time.time(), 3), "event": event, **fields, "prev": self._last_hash()}
        rec["hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()[:16]
        with self.path.open("a") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
        return rec

    def records(self) -> list[dict]:
        return [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]

    def verify(self) -> bool:
        prev = "genesis"
        for rec in self.records():
            body = {k: v for k, v in rec.items() if k != "hash"}
            if rec["prev"] != prev or hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16] != rec["hash"]:
                return False
            prev = rec["hash"]
        return True
