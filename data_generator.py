"""
data_generator.py
-----------------
Generates synthetic transactions.csv and settlements.csv with controlled
discrepancy scenarios injected for reconciliation testing.
"""

import csv
import random
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN

# Fixed seed for reproducibility
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

# ─── Configuration ────────────────────────────────────────────────────────────

NORMAL_TXN_COUNT      = 40          # base transactions before injections
SETTLEMENT_DELAY_DAYS = 1           # normal T+1 settlement
ROUNDING_BATCH_SIZE   = 7           # transactions in rounding mismatch batch
BASE_DATE             = datetime(2024, 3, 1)   # start of synthetic window

CUSTOMER_POOL = [f"CUST-{i:03d}" for i in range(1, 21)]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def _random_amount(lo=100.0, hi=5000.0) -> float:
    """Generate a realistic transaction amount."""
    return round(random.uniform(lo, hi), 2)

def _round_half_up(value: Decimal, places: int = 2) -> Decimal:
    quantizer = Decimal(10) ** -places
    return value.quantize(quantizer, rounding=ROUND_HALF_UP)

def _round_half_even(value: Decimal, places: int = 2) -> Decimal:
    quantizer = Decimal(10) ** -places
    return value.quantize(quantizer, rounding=ROUND_HALF_EVEN)


# ─── Normal data builder ──────────────────────────────────────────────────────

def _build_normal_records(start_id: int, count: int, start_date: datetime):
    """Return (transactions, settlements) list-of-dicts for normal records."""
    transactions = []
    settlements  = []

    for i in range(count):
        txn_id    = f"TXN-{start_id + i:03d}"
        ts        = start_date + timedelta(days=random.randint(0, 25),
                                           hours=random.randint(0, 23),
                                           minutes=random.randint(0, 59))
        amount    = _random_amount()
        txn_type  = random.choice(["payment", "payment", "payment", "refund"])
        cust_id   = random.choice(CUSTOMER_POOL)

        transactions.append({
            "txn_id":      txn_id,
            "timestamp":   _fmt_dt(ts),
            "customer_id": cust_id,
            "amount":      amount,
            "type":        txn_type,
        })

        # Normal settlement: T+1
        settle_dt = ts + timedelta(days=SETTLEMENT_DELAY_DAYS)
        settlements.append({
            "settlement_id":   f"SET-{start_id + i:03d}",
            "settlement_date": _fmt_dt(settle_dt),
            "txn_reference":   txn_id,
            "settled_amount":  amount,
        })

    return transactions, settlements


# ─── Discrepancy injectors ────────────────────────────────────────────────────

def _inject_timing_gap(txn_counter: int):
    """
    Scenario 1 – Timing Gap
    Transaction on March 31 settles on April 1 (crosses month boundary).
    """
    txn_id = f"TXN-{txn_counter:03d}"
    ts     = datetime(2024, 3, 31, 23, 45, 0)   # last moment of March
    amount = _random_amount(500, 2000)

    txn = {
        "txn_id":      txn_id,
        "timestamp":   _fmt_dt(ts),
        "customer_id": random.choice(CUSTOMER_POOL),
        "amount":      amount,
        "type":        "payment",
    }
    # Settlement arrives next month
    settle = {
        "settlement_id":   f"SET-{txn_counter:03d}",
        "settlement_date": _fmt_dt(datetime(2024, 4, 1, 9, 0, 0)),
        "txn_reference":   txn_id,
        "settled_amount":  amount,
    }
    return txn, settle


def _inject_duplicate_transaction(txn_counter: int):
    """
    Scenario 2 – Duplicate Transaction
    TXN appears twice in transactions but only once in settlements.
    """
    txn_id = "TXN-008"   # canonical duplicate ID for test assertions
    ts     = BASE_DATE + timedelta(days=5, hours=10)
    amount = _random_amount(200, 800)

    txn_original = {
        "txn_id":      txn_id,
        "timestamp":   _fmt_dt(ts),
        "customer_id": "CUST-005",
        "amount":      amount,
        "type":        "payment",
    }
    # Duplicate entry – same id, slightly different timestamp (re-submission)
    txn_duplicate = {
        "txn_id":      txn_id,
        "timestamp":   _fmt_dt(ts + timedelta(minutes=2)),
        "customer_id": "CUST-005",
        "amount":      amount,
        "type":        "payment",
    }
    settle = {
        "settlement_id":   f"SET-{txn_counter:03d}",
        "settlement_date": _fmt_dt(ts + timedelta(days=1)),
        "txn_reference":   txn_id,
        "settled_amount":  amount,
    }
    return [txn_original, txn_duplicate], settle


def _inject_rounding_mismatch(txn_counter: int):
    """
    Scenario 3 – Rounding Mismatch
    Platform uses ROUND_HALF_UP; bank uses ROUND_HALF_EVEN.
    Uses amounts ending in .X5 to guarantee divergence.
    Returns (transactions, settlements, expected_platform_total, expected_bank_total).
    """
    # Carefully chosen raw amounts where the two rounding modes differ
    raw_amounts = [
        Decimal("125.445"),
        Decimal("230.565"),
        Decimal("89.995"),
        Decimal("312.505"),
        Decimal("178.255"),
        Decimal("410.335"),
        Decimal("67.225"),
    ]

    transactions = []
    settlements  = []

    for idx, raw in enumerate(raw_amounts):
        txn_id        = f"TXN-{txn_counter + idx:03d}"
        platform_amt  = float(_round_half_up(raw))
        bank_amt      = float(_round_half_even(raw))
        ts            = BASE_DATE + timedelta(days=10 + idx, hours=9)
        cust_id       = random.choice(CUSTOMER_POOL)

        transactions.append({
            "txn_id":      txn_id,
            "timestamp":   _fmt_dt(ts),
            "customer_id": cust_id,
            "amount":      platform_amt,   # platform records ROUND_HALF_UP
            "type":        "payment",
        })
        settlements.append({
            "settlement_id":   f"SET-{txn_counter + idx:03d}",
            "settlement_date": _fmt_dt(ts + timedelta(days=1)),
            "txn_reference":   txn_id,
            "settled_amount":  bank_amt,   # bank records ROUND_HALF_EVEN
        })

    return transactions, settlements


def _inject_orphan_refund(txn_counter: int):
    """
    Scenario 4 – Orphan Refund
    A refund in transactions references TXN-999 which does not exist in settlements
    and has no original transaction record.
    """
    txn_id = "TXN-999"   # intentionally missing original
    ts     = BASE_DATE + timedelta(days=15, hours=14)
    amount = _random_amount(100, 500)

    txn = {
        "txn_id":      txn_id,
        "timestamp":   _fmt_dt(ts),
        "customer_id": "CUST-009",
        "amount":      amount,
        "type":        "refund",
    }
    # No corresponding settlement row
    return txn


# ─── Public API ───────────────────────────────────────────────────────────────

def generate_datasets(txn_path="transactions.csv", settle_path="settlements.csv"):
    """
    Orchestrates generation of both datasets and writes them to disk.
    Returns (transactions, settlements) as lists-of-dicts for downstream use.
    """
    all_txns    = []
    all_settles = []
    counter     = 50    # start normal IDs high to avoid clashing with injected IDs

    # ── Normal records ────────────────────────────────────────────────────────
    txns, settles = _build_normal_records(counter, NORMAL_TXN_COUNT, BASE_DATE)
    all_txns.extend(txns)
    all_settles.extend(settles)
    counter += NORMAL_TXN_COUNT

    # ── Scenario 1: Timing Gap ────────────────────────────────────────────────
    t_txn, t_settle = _inject_timing_gap(counter)
    all_txns.append(t_txn)
    all_settles.append(t_settle)
    counter += 1

    # ── Scenario 2: Duplicate ─────────────────────────────────────────────────
    dup_txns, dup_settle = _inject_duplicate_transaction(counter)
    all_txns.extend(dup_txns)     # two rows for same txn_id
    all_settles.append(dup_settle)
    counter += 1

    # ── Scenario 3: Rounding Mismatch ─────────────────────────────────────────
    r_txns, r_settles = _inject_rounding_mismatch(counter)
    all_txns.extend(r_txns)
    all_settles.extend(r_settles)
    counter += len(r_txns)

    # ── Scenario 4: Orphan Refund ─────────────────────────────────────────────
    orphan = _inject_orphan_refund(counter)
    all_txns.append(orphan)
    # deliberately NO settlement row for TXN-999

    # ── Shuffle to simulate realistic ordering ────────────────────────────────
    random.shuffle(all_txns)
    random.shuffle(all_settles)

    # ── Write CSVs ────────────────────────────────────────────────────────────
    _write_csv(txn_path, all_txns,
               ["txn_id", "timestamp", "customer_id", "amount", "type"])
    _write_csv(settle_path, all_settles,
               ["settlement_id", "settlement_date", "txn_reference", "settled_amount"])

    print(f"[DataGen] Written {len(all_txns)} transaction rows  → {txn_path}")
    print(f"[DataGen] Written {len(all_settles)} settlement rows → {settle_path}")

    return all_txns, all_settles


def _write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    generate_datasets()
