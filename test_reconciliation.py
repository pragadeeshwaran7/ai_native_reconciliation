"""
test_reconciliation.py
----------------------
Programmatic validation suite that asserts every injected discrepancy scenario
is correctly detected by the reconciliation engine.
"""

import sys
import traceback
from decimal import Decimal
from pathlib import Path

from data_generator import generate_datasets
from reconciliation_engine import ReconciliationEngine


# ─── Test harness ─────────────────────────────────────────────────────────────

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results: list[tuple[str, bool, str]] = []


def assert_test(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results.append((name, condition, detail))
    symbol = "✅" if condition else "❌"
    print(f"  {symbol} {name}" + (f"\n      {detail}" if detail and not condition else ""))


# ─── Individual test cases ────────────────────────────────────────────────────

def test_timing_gap(discrepancies: list[dict]):
    """
    The timing-gap transaction (March 31) must produce exactly one TIMING_MISMATCH
    discrepancy whose months span March → April.
    """
    timing = [d for d in discrepancies if d["discrepancy_type"] == "TIMING_MISMATCH"]
    found = any(
        d["detail"].get("txn_month") == "2024-03"
        and d["detail"].get("settle_month") == "2024-04"
        for d in timing
    )
    assert_test(
        "Timing Gap – month boundary detected",
        found,
        f"TIMING_MISMATCH records: {[d['txn_id'] for d in timing]}"
    )
    assert_test(
        "Timing Gap – at least one cross-month record",
        len(timing) >= 1,
        f"Count: {len(timing)}"
    )


def test_duplicate_transaction(discrepancies: list[dict]):
    """
    TXN-008 must appear in DUPLICATE_TRANSACTION discrepancies.
    """
    dups = [d for d in discrepancies if d["discrepancy_type"] == "DUPLICATE_TRANSACTION"]
    found_008 = any(d["txn_id"] == "TXN-008" for d in dups)
    assert_test(
        "Duplicate Transaction – TXN-008 flagged",
        found_008,
        f"Duplicate records: {[d['txn_id'] for d in dups]}"
    )
    assert_test(
        "Duplicate Transaction – occurrence count = 2",
        any(d["detail"].get("occurrences") == 2 for d in dups if d["txn_id"] == "TXN-008"),
        "Expected occurrences=2 in detail"
    )


def test_rounding_mismatch(discrepancies: list[dict], engine: ReconciliationEngine):
    """
    Aggregate rounding analysis must detect a non-zero delta ≤ ₹0.05
    across the rounding-batch transactions.
    """
    rr = engine.rounding_results
    delta = rr.get("aggregate_delta", Decimal("0"))

    assert_test(
        "Rounding Mismatch – aggregate delta > 0",
        delta > Decimal("0"),
        f"Aggregate delta: ₹{delta}"
    )
    assert_test(
        "Rounding Mismatch – aggregate delta ≤ ₹0.05",
        delta <= Decimal("0.05"),
        f"Aggregate delta: ₹{delta}"
    )

    agg_flag = [
        d for d in discrepancies
        if d["discrepancy_type"] == "AMOUNT_MISMATCH"
        and d["txn_id"] == "AGGREGATE_ROUNDING"
    ]
    assert_test(
        "Rounding Mismatch – AGGREGATE_ROUNDING discrepancy present",
        len(agg_flag) == 1,
        f"Found: {len(agg_flag)}"
    )


def test_orphan_refund(discrepancies: list[dict]):
    """
    TXN-999 refund (no parent payment) must be flagged as ORPHAN_REFUND.
    """
    orphans = [d for d in discrepancies if d["discrepancy_type"] == "ORPHAN_REFUND"]
    found_999 = any(d["txn_id"] == "TXN-999" for d in orphans)
    assert_test(
        "Orphan Refund – TXN-999 flagged",
        found_999,
        f"Orphan records: {[d['txn_id'] for d in orphans]}"
    )


def test_no_false_positives(discrepancies: list[dict], transactions: list[dict]):
    """
    Normal transactions (not in injected IDs) should not generate DUPLICATE
    or ORPHAN_REFUND false positives.
    """
    injected_ids = {"TXN-008", "TXN-999"}
    spurious_dups = [
        d for d in discrepancies
        if d["discrepancy_type"] == "DUPLICATE_TRANSACTION"
        and d["txn_id"] not in injected_ids
    ]
    assert_test(
        "No false-positive duplicates on normal transactions",
        len(spurious_dups) == 0,
        f"Spurious: {[d['txn_id'] for d in spurious_dups]}"
    )

    injected_orphan_ids = {"TXN-999"}
    spurious_orphans = [
        d for d in discrepancies
        if d["discrepancy_type"] == "ORPHAN_REFUND"
        and d["txn_id"] not in injected_orphan_ids
    ]
    assert_test(
        "No false-positive orphan refunds on normal transactions",
        len(spurious_orphans) == 0,
        f"Spurious: {[d['txn_id'] for d in spurious_orphans]}"
    )


# ─── Runner ───────────────────────────────────────────────────────────────────

def run_all_tests():
    print("\n" + "═" * 60)
    print("  PAYMENT RECONCILIATION – VALIDATION SUITE")
    print("═" * 60)

    # Generate fresh datasets
    print("\n[Setup] Generating datasets…")
    txns, settles = generate_datasets(
        txn_path="transactions.csv",
        settle_path="settlements.csv"
    )

    # Run reconciliation
    print("\n[Setup] Running reconciliation engine…")
    engine = ReconciliationEngine()
    engine.load()
    engine.run()

    discrepancies = engine.discrepancies

    print(f"\n[Setup] Detected {len(discrepancies)} total discrepancies\n")
    print("─" * 60)

    # Run tests
    print("\n📋 Scenario 1 – Timing Gap")
    test_timing_gap(discrepancies)

    print("\n📋 Scenario 2 – Duplicate Transaction")
    test_duplicate_transaction(discrepancies)

    print("\n📋 Scenario 3 – Rounding Mismatch")
    test_rounding_mismatch(discrepancies, engine)

    print("\n📋 Scenario 4 – Orphan Refund")
    test_orphan_refund(discrepancies)

    print("\n📋 Regression – No False Positives")
    test_no_false_positives(discrepancies, txns)

    # Summary
    passed = sum(1 for _, ok, _ in results if ok)
    total  = len(results)
    print("\n" + "═" * 60)
    print(f"  RESULTS: {passed}/{total} tests passed")
    print("═" * 60 + "\n")

    if passed < total:
        print("Failed tests:")
        for name, ok, detail in results:
            if not ok:
                print(f"  ❌ {name}")
                if detail:
                    print(f"     {detail}")
        sys.exit(1)
    else:
        print("All tests passed ✅\n")


if __name__ == "__main__":
    run_all_tests()
