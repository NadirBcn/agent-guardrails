# agent-guardrails

Small, dependency-free guardrails for LLM agents that act in the real world: spend money, send messages, launch
campaigns. Four pieces, each with tests:

| Piece | What it guarantees |
|---|---|
| `Approvals` | An external action runs only with an approval for that **exact** action, target and payload. Approvals expire and are consumed on first use, so "approve this email" does not approve an edited email or a second send. |
| `SpendLedger` | **Reserve-then-settle.** The worst-case cost is booked before a paid call and settled to the real cost after. A crash between the two leaves the reservation in place, so failures can never let spend escape the cap. A call that was sent but has an unknown cost cannot be released or blindly retried. |
| `KillSwitch` | Stop rules written before launch ("35 euros spent with zero sales"). Once tripped, every guarded tool refuses until a human resets it with a written reason. |
| `AuditLog` | Append-only, hash-chained JSONL. `verify()` detects any edited or deleted line. |

`GuardedTool` wires them together: wrap any tool function, declare its risk (`READ`, `SPEND`, `EXTERNAL`) and its
worst-case cost, and the agent can only reach it through the checks.

This is a clean reference version of patterns I run in production on a self-hosted agent that operates ad accounts, a
store and outbound email. The demo uses a fake ad platform; nothing here talks to a real API.

## Demo

```bash
pip install -e ".[dev]"
python examples/demo_ads_agent.py
pytest -q
```

The demo agent tries to launch three ad variants. The owner approves two and declines the third, which never launches.
The two live campaigns spend hourly against a 50 euro cap until the pre-written kill rule fires (35 euros with no sales).
The rule is checked after each call, so it can overshoot by one call: in the demo it stops at 38.25, and the per-call
cap bounds that overshoot. If you need a hard ceiling, that is the ledger's job, not the kill rule's.

## Design notes

- **Gate only what leaves the building.** Reads and reversible internal work run freely; approvals are for sends,
  spend, posts, purchases and deletions. Gating everything trains people to click "approve" without reading.
- **Worst case first.** Providers sometimes accept a request and then time out. Treating that as "unknown, reserved at
  worst case" is what keeps a retry loop from double-spending.
- **Stop rules are decided before the data arrives.** Deciding them afterwards is how a losing test keeps running "one
  more day".

MIT licence.
