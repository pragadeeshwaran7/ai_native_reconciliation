"""
reconciliation_engine.py
------------------------
Core pipeline that loads transactions & settlements, joins them, and flags
every discrepancy category with structured output.
"""

import csv
import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any

# ─── Configuration ────────────────────────────────────────────────────────────

AMOUNT_TOLERANCE      = Decimal("0.01")   # max allowed per-txn amount delta (₹)
ROUNDING_AGG_TOLERANCE= Decimal("0.05")   # max allowed aggregate rounding delta (₹)
SETTLEMENT_DELAY_DAYS = 1                 # expected T+N settlement window
NORMAL_SETTLE_MAX_DAYS= 3                 # anything beyond = timing flag candidate

DISCREPANCY_TYPES = {
    "MISSING_SETTLEMENT":   "Transaction has no matching settlement",
    "TIMING_MISMATCH":      "Transaction and settlement fall in different calendar months",
    "DUPLICATE_TRANSACTION":"Same txn_id appears more than once in transactions",
    "AMOUNT_MISMATCH":      "Settled amount differs from transaction amount beyond tolerance",
    "ORPHAN_REFUND":        "Refund references a txn_id with no parent payment",
}


# ─── Data loaders ─────────────────────────────────────────────────────────────

def _parse_dt(s: str) -> datetime:
    return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S")

def load_transactions(path="transactions.csv") -> list[dict]:
    """Load transactions CSV; coerce types."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "txn_id":      r["txn_id"].strip(),
                "timestamp":   _parse_dt(r["timestamp"]),
                "customer_id": r["customer_id"].strip(),
                "amount":      Decimal(r["amount"]).quantize(Decimal("0.01")),
                "type":        r["type"].strip(),
            })
    return rows

def load_settlements(path="settlements.csv") -> list[dict]:
    """Load settlements CSV; coerce types."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "settlement_id":   r["settlement_id"].strip(),
                "settlement_date": _parse_dt(r["settlement_date"]),
                "txn_reference":   r["txn_reference"].strip(),
                "settled_amount":  Decimal(r["settled_amount"]).quantize(Decimal("0.01")),
            })
    return rows


# ─── Detection helpers ────────────────────────────────────────────────────────

def _detect_duplicates(transactions: list[dict]) -> dict[str, list[dict]]:
    """Return mapping txn_id → [rows] for every txn_id that appears > 1 time."""
    seen: dict[str, list[dict]] = defaultdict(list)
    for row in transactions:
        seen[row["txn_id"]].append(row)
    return {tid: rows for tid, rows in seen.items() if len(rows) > 1}

def _build_settlement_map(settlements: list[dict]) -> dict[str, list[dict]]:
    """Index settlements by txn_reference (1:many supported)."""
    index: dict[str, list[dict]] = defaultdict(list)
    for row in settlements:
        index[row["txn_reference"]].append(row)
    return index

def _build_payment_ids(transactions: list[dict]) -> set[str]:
    """
    Return set of txn_ids that are payment type.
    An orphan refund is a refund whose OWN txn_id has no matching payment row
    AND has no settlement record — meaning it references a non-existent original.
    In our model, each transaction has a unique txn_id; a refund is only "orphan"
    if its txn_id never appears as a payment anywhere in the transaction log.
    """
    return {r["txn_id"] for r in transactions if r["type"] == "payment"}

def _rounding_delta(amount_str: Decimal) -> tuple[Decimal, Decimal]:
    """
    Return (platform_rounded, bank_rounded) for a raw amount.
    Platform: ROUND_HALF_UP  |  Bank: ROUND_HALF_EVEN
    These differ only for amounts ending exactly at .X5.
    """
    q = Decimal("0.01")
    platform = amount_str.quantize(q, rounding=ROUND_HALF_UP)
    bank      = amount_str.quantize(q, rounding=ROUND_HALF_EVEN)
    return platform, bank


# ─── Main reconciliation pipeline ────────────────────────────────────────────

class ReconciliationEngine:
    """
    Stateful pipeline:
      1. load()  – ingest CSV data
      2. run()   – execute all detection checks
      3. report()– return structured discrepancy list
    """

    def __init__(self, txn_path="transactions.csv", settle_path="settlements.csv"):
        self.txn_path    = txn_path
        self.settle_path = settle_path

        self.transactions: list[dict] = []
        self.settlements:  list[dict] = []
        self.discrepancies: list[dict] = []

        # Aggregated rounding analysis results stored for test access
        self.rounding_results: dict[str, Any] = {}

    # ── Stage 1: Load ─────────────────────────────────────────────────────────

    def load(self):
        self.transactions = load_transactions(self.txn_path)
        self.settlements  = load_settlements(self.settle_path)
        print(f"[Engine] Loaded {len(self.transactions)} transactions, "
              f"{len(self.settlements)} settlements")

    # ── Stage 2: Run all checks ───────────────────────────────────────────────

    def run(self) -> list[dict]:
        self.discrepancies = []

        dup_map      = _detect_duplicates(self.transactions)
        settle_map   = _build_settlement_map(self.settlements)
        payment_ids  = _build_payment_ids(self.transactions)

        # De-duplicate transactions for primary joins (keep first occurrence)
        seen_ids: set[str] = set()
        unique_txns: list[dict] = []
        for row in self.transactions:
            if row["txn_id"] not in seen_ids:
                unique_txns.append(row)
                seen_ids.add(row["txn_id"])

        # ── Check A: Duplicate transactions ───────────────────────────────────
        for tid, rows in dup_map.items():
            self._flag({
                "discrepancy_type":  "DUPLICATE_TRANSACTION",
                "txn_id":            tid,
                "description":       f"txn_id appears {len(rows)} times in transactions",
                "transaction_amount":str(rows[0]["amount"]),
                "settled_amount":    None,
                "txn_timestamp":     str(rows[0]["timestamp"]),
                "settlement_date":   None,
                "detail":            {
                    "occurrences": len(rows),
                    "timestamps":  [str(r["timestamp"]) for r in rows],
                },
            })

        # ── Check B: Orphan refunds ───────────────────────────────────────────
        # An orphan refund is a refund that:
        #   (a) has no settlement record (unresolved), AND
        #   (b) its txn_id does not appear as a payment in the transaction log
        # Normal refunds with settlements are valid and not flagged here.
        for row in unique_txns:
            if row["type"] == "refund":
                has_settlement = bool(settle_map.get(row["txn_id"]))
                is_orphan      = (not has_settlement) and (row["txn_id"] not in payment_ids)
                if is_orphan:
                    self._flag({
                        "discrepancy_type":  "ORPHAN_REFUND",
                        "txn_id":            row["txn_id"],
                        "description":       "Refund has no settlement and no corresponding parent payment",
                        "transaction_amount":str(row["amount"]),
                        "settled_amount":    None,
                        "txn_timestamp":     str(row["timestamp"]),
                        "settlement_date":   None,
                        "detail":            {},
                    })

        # ── Checks C/D/E: Per-transaction join analysis ───────────────────────
        for txn in unique_txns:
            tid       = txn["txn_id"]
            txn_month = (txn["timestamp"].year, txn["timestamp"].month)
            matches   = settle_map.get(tid, [])

            # C – Missing settlement
            if not matches:
                # Skip refunds that will be flagged as ORPHAN (no settlement + no parent)
                is_orphan_refund = (
                    txn["type"] == "refund"
                    and tid not in payment_ids
                )
                if not is_orphan_refund:
                    self._flag({
                        "discrepancy_type":  "MISSING_SETTLEMENT",
                        "txn_id":            tid,
                        "description":       "No settlement record found for transaction",
                        "transaction_amount":str(txn["amount"]),
                        "settled_amount":    None,
                        "txn_timestamp":     str(txn["timestamp"]),
                        "settlement_date":   None,
                        "detail":            {},
                    })
                continue

            # Evaluate each matched settlement (1:1 assumed; 1:many supported)
            for settle in matches:
                s_month = (settle["settlement_date"].year,
                           settle["settlement_date"].month)

                # D – Timing mismatch (crosses calendar month)
                if txn_month != s_month:
                    self._flag({
                        "discrepancy_type":  "TIMING_MISMATCH",
                        "txn_id":            tid,
                        "description":       (
                            f"Transaction in {txn_month[0]}-{txn_month[1]:02d} "
                            f"settled in {s_month[0]}-{s_month[1]:02d}"
                        ),
                        "transaction_amount":str(txn["amount"]),
                        "settled_amount":    str(settle["settled_amount"]),
                        "txn_timestamp":     str(txn["timestamp"]),
                        "settlement_date":   str(settle["settlement_date"]),
                        "detail":            {
                            "txn_month":    f"{txn_month[0]}-{txn_month[1]:02d}",
                            "settle_month": f"{s_month[0]}-{s_month[1]:02d}",
                        },
                    })

                # E – Amount mismatch beyond tolerance
                delta = abs(txn["amount"] - settle["settled_amount"])
                if delta > AMOUNT_TOLERANCE:
                    self._flag({
                        "discrepancy_type":  "AMOUNT_MISMATCH",
                        "txn_id":            tid,
                        "description":       (
                            f"Amount delta ₹{delta} exceeds tolerance ₹{AMOUNT_TOLERANCE}"
                        ),
                        "transaction_amount":str(txn["amount"]),
                        "settled_amount":    str(settle["settled_amount"]),
                        "txn_timestamp":     str(txn["timestamp"]),
                        "settlement_date":   str(settle["settlement_date"]),
                        "detail":            {
                            "delta":     str(delta),
                            "tolerance": str(AMOUNT_TOLERANCE),
                        },
                    })

        # ── Check F: Aggregate rounding mismatch ──────────────────────────────
        self._check_aggregate_rounding(unique_txns, settle_map)

        return self.discrepancies

    def _check_aggregate_rounding(self, unique_txns, settle_map):
        """
        Detect aggregate rounding drift: sum platform amounts vs sum bank amounts
        for transactions that have matching settlements with tiny per-row deltas
        (≤ ₹0.01 each, but collectively significant).
        """
        platform_total = Decimal("0")
        bank_total     = Decimal("0")
        affected_ids   = []

        for txn in unique_txns:
            matches = settle_map.get(txn["txn_id"], [])
            if not matches:
                continue
            for settle in matches:
                delta = abs(txn["amount"] - settle["settled_amount"])
                # Each individual delta is within tolerance but non-zero
                if Decimal("0") < delta <= AMOUNT_TOLERANCE:
                    platform_total += txn["amount"]
                    bank_total     += settle["settled_amount"]
                    affected_ids.append(txn["txn_id"])

        agg_delta = abs(platform_total - bank_total)
        self.rounding_results = {
            "affected_txns":    affected_ids,
            "platform_total":   platform_total,
            "bank_total":       bank_total,
            "aggregate_delta":  agg_delta,
        }

        if agg_delta > Decimal("0") and agg_delta <= ROUNDING_AGG_TOLERANCE:
            self._flag({
                "discrepancy_type":  "AMOUNT_MISMATCH",
                "txn_id":            "AGGREGATE_ROUNDING",
                "description":       (
                    f"Aggregate rounding drift of ₹{agg_delta} detected across "
                    f"{len(affected_ids)} transactions (platform ROUND_HALF_UP vs "
                    f"bank ROUND_HALF_EVEN)"
                ),
                "transaction_amount":str(platform_total),
                "settled_amount":    str(bank_total),
                "txn_timestamp":     None,
                "settlement_date":   None,
                "detail":            {
                    "affected_txns":   affected_ids,
                    "aggregate_delta": str(agg_delta),
                },
            })

    def _flag(self, record: dict):
        self.discrepancies.append(record)

    # ── Stage 3: Reports ──────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Return high-level reconciliation summary."""
        counts: dict[str, int] = defaultdict(int)
        for d in self.discrepancies:
            counts[d["discrepancy_type"]] += 1

        return {
            "total_transactions":       len(self.transactions),
            "unique_transactions":      len({r["txn_id"] for r in self.transactions}),
            "total_settlements":        len(self.settlements),
            "discrepancy_counts":       dict(counts),
            "total_discrepancies":      len(self.discrepancies),
            "amount_tolerance":         str(AMOUNT_TOLERANCE),
            "settlement_delay_assumed": f"T+{SETTLEMENT_DELAY_DAYS}",
        }

    def write_reports(self,
                      detail_path="discrepancy_report.json",
                      summary_path="summary_report.json"):
        """Persist both reports to disk."""
        summary = self.summary()

        with open(detail_path, "w", encoding="utf-8") as f:
            json.dump(self.discrepancies, f, indent=2, default=str)

        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        print(f"[Engine] Discrepancy report → {detail_path}")
        print(f"[Engine] Summary report     → {summary_path}")

        return detail_path, summary_path


if __name__ == "__main__":
    engine = ReconciliationEngine()
    engine.load()
    engine.run()
    engine.write_reports()
    import json
    print(json.dumps(engine.summary(), indent=2))
