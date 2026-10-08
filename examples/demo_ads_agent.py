"""Demo: an ad-testing agent with a fake ad platform.

The agent wants to launch three ad variants at 20 euros each and keep spending while results come in. Guardrails:
- launching a campaign is an EXTERNAL action: it needs an exact approval of the campaign payload;
- every API call reserves its worst-case cost first; the daily cap is 50 euros;
- a kill rule written before launch stops everything if spend reaches 35 euros with zero sales.

Run: python examples/demo_ads_agent.py
"""
import random
import tempfile
from pathlib import Path

from guardrails import (ApprovalRequired, Approvals, AuditLog, BudgetExceeded, GuardedTool, KillRule, KillSwitch, Risk,
                        SpendLedger, Tripped)

random.seed(7)


def fake_launch(target, variant, daily_budget):
    return {"campaign": f"cmp-{variant}", "status": "live"}, 0.0


def fake_spend_hour(target, campaign):
    spent = round(random.uniform(3.5, 6.0), 2)
    return {"campaign": campaign, "spent": spent, "sales": 0}, spent


def main():
    tmp = Path(tempfile.mkdtemp())
    ledger = SpendLedger(tmp / "ledger.json", cap=50.0, per_call_cap=8.0)
    approvals = Approvals()
    audit = AuditLog(tmp / "audit.jsonl")
    kill = KillSwitch([KillRule("no_sales", lambda m: m.get("spend", 0) >= 35 and m.get("sales", 0) == 0,
                                "35 euros spent with zero sales")])
    common = dict(ledger=ledger, approvals=approvals, audit=audit, kill=kill)
    launch = GuardedTool("launch_campaign", fake_launch, Risk.EXTERNAL, 0.0, **common)
    run_hour = GuardedTool("run_hour", fake_spend_hour, Risk.SPEND, 8.0, **common)

    live = []
    for v in ["hook-a", "hook-b", "hook-c"]:
        try:
            live.append(launch("ads-account", variant=v, daily_budget=20)["campaign"])
        except ApprovalRequired as e:
            print(f"needs approval: {e.request.action} {e.request.payload} [{e.request.digest}]")
            if v != "hook-c":   # the owner approves two of three variants
                approvals.grant(e.request.digest, "owner", f"variant {v} copy reviewed")
                live.append(launch("ads-account", variant=v, daily_budget=20)["campaign"])
            else:
                print("  owner declined hook-c, it never launches")

    hour = 0
    try:
        while True:
            hour += 1
            for c in live:
                r = run_hour("ads-account", campaign=c)
                print(f"hour {hour}: {c} spent {r['spent']:.2f} | committed {ledger.committed():.2f} / 50")
    except Tripped as t:
        print(f"STOPPED by kill rule -> {t}")
    except BudgetExceeded as b:
        print(f"STOPPED by budget -> {b}")
    print(f"audit entries: {len(audit.records())}, chain intact: {audit.verify()}")


if __name__ == "__main__":
    main()
