"""
main.py
-------
Entry point: generates data, runs reconciliation, prints assumptions, writes
reports, and launches the optional dashboard.
"""

import json
import sys
from pathlib import Path

from data_generator import generate_datasets
from reconciliation_engine import ReconciliationEngine

ASSUMPTIONS = """
╔══════════════════════════════════════════════════════════════════════════════╗
║              PAYMENT RECONCILIATION SYSTEM – ASSUMPTIONS                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  1. Settlement Delay Rules                                                   ║
║     • Expected settlement window: T+1 (next business day).                  ║
║     • Settlements arriving > T+3 are candidates for timing flags.           ║
║     • Cross-month settlements (txn in month M, settlement in month M+1)     ║
║       are always flagged regardless of the day gap.                         ║
║                                                                              ║
║  2. Matching Tolerance Logic                                                 ║
║     • Per-transaction amount tolerance: ₹0.01.                              ║
║     • Differences ≤ ₹0.01 on individual rows are accepted.                  ║
║     • Aggregate rounding drift tolerance: ₹0.05 across a batch.            ║
║     • Both tolerances are configurable via constants in the engine.         ║
║                                                                              ║
║  3. Handling of Refunds vs Payments                                          ║
║     • A refund is expected to reference an existing payment txn_id.         ║
║     • Refunds with no matching parent payment are flagged ORPHAN_REFUND.    ║
║     • Refunds that have settlements follow the same amount-match checks.    ║
║     • Refunds without settlements are flagged MISSING_SETTLEMENT only if    ║
║       they are NOT already flagged as orphans (to avoid double-counting).   ║
║                                                                              ║
║  4. Settlement Cardinality (1:1 vs 1:many)                                  ║
║     • The engine supports 1:many (a single txn_id can have multiple         ║
║       settlement rows, e.g. partial settlements).                            ║
║     • Each settlement row is evaluated independently against its parent.    ║
║     • The common case in generated data is 1:1.                             ║
║                                                                              ║
║  5. Rounding Convention                                                      ║
║     • Platform applies ROUND_HALF_UP (standard commercial rounding).        ║
║     • Bank applies ROUND_HALF_EVEN (banker's rounding / IEEE 754 default).  ║
║     • Only amounts ending exactly at .X5 diverge between the two methods.   ║
║                                                                              ║
║  6. Duplicate Detection                                                      ║
║     • Duplicate = same txn_id appears > 1 time in transactions.csv.         ║
║     • The engine joins on the first occurrence only to avoid cascading      ║
║       false positives in downstream checks.                                 ║
║                                                                              ║
║  7. Reproducibility                                                          ║
║     • Random seed fixed at 42; all generated data is deterministic.         ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""


def main(launch_dashboard: bool = False):
    print(ASSUMPTIONS)

    # ── Step 1: Generate synthetic datasets ───────────────────────────────────
    print("━" * 70)
    print("  [1/3] Generating datasets")
    print("━" * 70)
    generate_datasets(txn_path="transactions.csv", settle_path="settlements.csv")

    # ── Step 2: Run reconciliation ────────────────────────────────────────────
    print("\n" + "━" * 70)
    print("  [2/3] Running reconciliation engine")
    print("━" * 70)
    engine = ReconciliationEngine()
    engine.load()
    engine.run()
    engine.write_reports(
        detail_path="discrepancy_report.json",
        summary_path="summary_report.json"
    )

    # ── Step 3: Print summary ─────────────────────────────────────────────────
    print("\n" + "━" * 70)
    print("  [3/3] Reconciliation Summary")
    print("━" * 70)
    summary = engine.summary()
    print(json.dumps(summary, indent=2))

    print("\n  Discrepancy Breakdown:")
    for dtype, count in summary["discrepancy_counts"].items():
        print(f"    • {dtype:<30} {count}")

    print("\n  Rounding Analysis:")
    rr = engine.rounding_results
    if rr:
        print(f"    • Platform total   : ₹{rr['platform_total']}")
        print(f"    • Bank total       : ₹{rr['bank_total']}")
        print(f"    • Aggregate delta  : ₹{rr['aggregate_delta']}")
        print(f"    • Affected txns    : {len(rr['affected_txns'])}")

    print("\n  Output files:")
    for p in ["transactions.csv", "settlements.csv",
              "discrepancy_report.json", "summary_report.json"]:
        size = Path(p).stat().st_size if Path(p).exists() else 0
        print(f"    📄 {p:<35} ({size:,} bytes)")

    # ── Optional: Dashboard ───────────────────────────────────────────────────
    if launch_dashboard:
        try:
            import subprocess
            subprocess.Popen(["streamlit", "run", "dashboard.py"])
            print("\n  🚀 Dashboard launched at http://localhost:8501")
        except FileNotFoundError:
            print("\n  ⚠  Streamlit not installed. Run: pip install streamlit")


if __name__ == "__main__":
    launch = "--dashboard" in sys.argv
    main(launch_dashboard=launch)
