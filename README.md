# ReconSync: Payment Reconciliation System 💰

A high-performance payment reconciliation pipeline and interactive dashboard designed to detect and visualize discrepancies between platform transaction records and bank settlement reports.

![System Health](https://img.shields.io/badge/SYSTEM-HEALTHY-emerald?style=for-the-badge)
![Tests](https://img.shields.io/badge/TESTS-10%2F10%20PASSING-blue?style=for-the-badge)

## 🎯 Overview

ReconSync simulates a real-world fintech environment where platform ledgers and bank statements must be reconciled. It automatically injects complex discrepancy scenarios—such as timing gaps, duplicate entries, and rounding mismatches—and provides a premium visualization layer for data engineers and financial analysts.

---

## 🚀 Key Features

- **Synthetic Data Generation**: Reproducible datasets with controlled discrepancy injection.
- **Advanced Detection Engine**:
  - **Timing Mismatches**: Detects cross-month settlement delays.
  - **Duplicate Detection**: Flags multiple platform entries for single settlements.
  - **Rounding Analysis**: Identifies aggregate drift between `ROUND_HALF_UP` (Platform) and `ROUND_HALF_EVEN` (Bank).
  - **Orphan Refund Tracking**: Flags refunds referencing non-existent parent transactions.
- **Interactive Dashboard**: Premium dark-mode visualization built with Vanilla JS/CSS (no heavy frameworks required).
- **Programmatic Validation**: 10/10 automated test cases ensuring zero false positives.

---

## 🛠️ Tech Stack

- **Backend**: Python 3.11+ (Decimal-safe arithmetic)
- **Frontend**: HTML5, CSS3 (Glassmorphism), Vanilla JavaScript
- **Data**: CSV, JSON
- **Visualization**: Custom CSS-based charts (Bars, Donut)

---

## 📂 Project Structure

```text
├── dashboard/               # Premium Visualization Layer
│   ├── index.html           # Dashboard Shell
│   ├── styles.css           # Glassmorphism Design System
│   └── app.js               # Data Rendering & Interactivity
├── data_generator.py        # Scenario Injection & CSV Generation
├── reconciliation_engine.py  # Core Reconciliation Logic
├── test_reconciliation.py   # 10/10 Automated Test Suite
├── main.py                  # Pipeline Orchestrator & CLI
├── .gitignore               # Python environment exclusions
└── *.csv / *.json           # Generated Data & Reports
```

---

## 📖 How to Run

### 1. Generate Data & Run Reconciliation
Run the main pipeline to generate fresh synthetic datasets and perform the reconciliation.

```bash
python main.py
```

### 2. Run Validation Suite
Verify that all discrepancy detection logic is working perfectly.

```bash
python test_reconciliation.py
```

### 3. Launch the Dashboard
Serve the dashboard locally to explore the discrepancies visually.

```bash
cd dashboard
python -m http.server 8080
```
Then navigate to `http://localhost:8080` in your browser.

---

## 🧠 System Assumptions

1. **Settlement Delay**: Expected window is **T+1**. Settlements crossing month boundaries are always flagged.
2. **Tolerance**: Per-transaction amount tolerance is **₹0.01**. Aggregate rounding drift tolerance is **₹0.05**.
3. **Rounding**: Platform uses `ROUND_HALF_UP` (Commercial), Bank uses `ROUND_HALF_EVEN` (Bankers).
4. **Duplicates**: Joined on the first occurrence to prevent cascading false positives.

---

## 📊 Discrepancy Scenarios Injected

1. **Timing Gap**: TXN on March 31 settled on April 1.
2. **Duplicate Transaction**: `TXN-008` appears twice in ledger but once in bank settlement.
3. **Rounding Mismatch**: Batch of 7 transactions ending in `.X5` causing aggregate drift.
4. **Orphan Refund**: `TXN-999` refund with no corresponding payment record.

---

*Built with ❤️ for AI-Native Data Engineering.*
