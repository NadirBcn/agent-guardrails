import pytest

from guardrails import (ApprovalRequired, Approvals, AuditLog, BudgetExceeded, GuardedTool, KillRule, KillSwitch, Risk,
                        SpendLedger, Tripped)


@pytest.fixture
def kit(tmp_path):
    ledger = SpendLedger(tmp_path / "ledger.json", cap=10.0, per_call_cap=4.0)
    approvals = Approvals(ttl_seconds=60)
    audit = AuditLog(tmp_path / "audit.jsonl")
    kill = KillSwitch([KillRule("loss", lambda m: m.get("spend", 0) >= 7, "spent 7 with no result")])
    return ledger, approvals, audit, kill


def fake_send(target, body):
    return f"sent to {target}", 1.5


def make(kit, fn=fake_send, risk=Risk.EXTERNAL, worst=2.0):
    ledger, approvals, audit, kill = kit
    return GuardedTool("send_email", fn, risk, worst, ledger, approvals, audit, kill)


def test_external_action_needs_exact_approval(kit):
    tool = make(kit)
    with pytest.raises(ApprovalRequired) as e:
        tool("ana@example.com", body="Hello Ana")
    kit[1].grant(e.value.request.digest, "owner", "copy checked and approved")
    assert tool("ana@example.com", body="Hello Ana") == "sent to ana@example.com"


def test_approval_does_not_cover_a_different_payload_or_a_second_send(kit):
    tool = make(kit)
    r = kit[1].request("send_email", "ana@example.com", {"body": "Hello Ana"})
    kit[1].grant(r.digest, "owner", "copy checked and approved")
    with pytest.raises(ApprovalRequired):
        tool("ana@example.com", body="Hello Ana, plus a discount")   # changed copy
    tool("ana@example.com", body="Hello Ana")
    with pytest.raises(ApprovalRequired):
        tool("ana@example.com", body="Hello Ana")                     # consumed


def test_approval_expires(kit):
    now = [1000.0]
    kit[1].clock = lambda: now[0]
    r = kit[1].request("send_email", "bo@example.com", {"body": "Hi"})
    kit[1].grant(r.digest, "owner", "approved for today only")
    now[0] += 61
    with pytest.raises(ApprovalRequired):
        make(kit)("bo@example.com", body="Hi")


def test_reserve_blocks_before_spending(kit):
    ledger = kit[0]
    ledger.reserve(4.0, "a"); ledger.reserve(4.0, "b")
    with pytest.raises(BudgetExceeded):
        ledger.reserve(3.0, "c")                                       # 8 + 3 > 10
    with pytest.raises(BudgetExceeded):
        ledger.reserve(5.0, "d")                                       # per-call cap


def test_settle_frees_the_difference(kit):
    ledger = kit[0]
    rid = ledger.reserve(4.0, "a"); ledger.mark_sent(rid); ledger.settle(rid, 1.0)
    assert ledger.committed() == 1.0


def test_crash_after_send_keeps_worst_case_reserved(kit):
    def boom(target, body):
        raise TimeoutError("provider timed out after accepting the request")
    tool = make(kit, fn=boom, risk=Risk.SPEND, worst=3.0)
    with pytest.raises(TimeoutError):
        tool("api", body="x")
    assert kit[0].committed() == 3.0                                   # not released, not retried
    with pytest.raises(ValueError):
        rid = next(iter(kit[0]._load()["entries"]))
        kit[0].release(rid)                                            # sent calls cannot be released


def test_kill_switch_trips_and_needs_a_reasoned_reset(kit):
    tool = make(kit, risk=Risk.SPEND, worst=2.0)
    for _ in range(5):
        try:
            tool("api", body="x")
        except Tripped:
            break
    with pytest.raises(Tripped):
        tool("api", body="x")
    with pytest.raises(ValueError):
        kit[3].reset("owner", "ok")
    kit[3].reset("owner", "reviewed spend, rule raised to 9")


def test_audit_log_is_tamper_evident(kit, tmp_path):
    audit = kit[2]
    audit.write("a", x=1); audit.write("b", x=2)
    assert audit.verify()
    lines = audit.path.read_text().splitlines()
    audit.path.write_text(lines[0].replace('"x": 1', '"x": 9') + "\n" + lines[1] + "\n")
    assert not audit.verify()
