// ─── Data Loading ────────────────────────────────────────────────────────────

let SUMMARY = {};
let DISCREPANCIES = [];
let ROUNDING = {};
const ASSUMPTIONS = [
  { title: "Settlement Delay", text: "Expected T+1 settlement. Cross-month settlements always flagged regardless of day gap." },
  { title: "Amount Tolerance", text: "Per-transaction tolerance: ₹0.01. Aggregate rounding drift tolerance: ₹0.05." },
  { title: "Refunds vs Payments", text: "Refunds must reference existing payment txn_id. Orphan refunds (no parent) are flagged separately." },
  { title: "Cardinality", text: "Engine supports 1:many settlements per txn_id. Each settlement row evaluated independently." },
  { title: "Rounding Convention", text: "Platform: ROUND_HALF_UP. Bank: ROUND_HALF_EVEN. Diverges only on .X5 amounts." },
  { title: "Reproducibility", text: "Random seed fixed at 42. All generated data is deterministic across runs." }
];

async function loadData() {
  try {
    const [summaryRes, reportRes] = await Promise.all([
      fetch('./summary_report.json'),
      fetch('./discrepancy_report.json')
    ]);

    SUMMARY = await summaryRes.json();
    DISCREPANCIES = await reportRes.json();

    // Reconstruct rounding data from summary/report if needed, or just extract from report
    const aggRounding = DISCREPANCIES.find(d => d.txn_id === 'AGGREGATE_ROUNDING');
    ROUNDING = {
      platform_total: parseFloat(aggRounding?.transaction_amount || 0),
      bank_total: parseFloat(aggRounding?.settled_amount || 0),
      aggregate_delta: parseFloat(aggRounding?.detail?.aggregate_delta || 0),
      affected_txns: aggRounding?.detail?.affected_txns || []
    };

    renderStats();
    renderDiscrepancyFilters();
    renderDiscrepancyCards();
    renderBarChart();
    renderDonut();
    renderRounding();
    renderTable();
    renderAssumptions();
  } catch (err) {
    console.error("Failed to load reconciliation data:", err);
    document.body.innerHTML = `<div style="padding:2rem; color:white; text-align:center;">
      <h2>⚠️ Error Loading Data</h2>
      <p>Please ensure 'summary_report.json' and 'discrepancy_report.json' exist in the root directory.</p>
    </div>`;
  }
}

// ─── DOM helpers ─────────────────────────────────────────────────────────────

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ─── Render functions ────────────────────────────────────────────────────────

function renderStats() {
  const container = $('#stats-row');
  const matched = SUMMARY.total_settlements;
  const matchRate = ((matched / SUMMARY.unique_transactions) * 100).toFixed(1);

  const cards = [
    { label: 'Total Transactions', value: SUMMARY.total_transactions, sub: `${SUMMARY.unique_transactions} unique`, cls: 'blue' },
    { label: 'Settlements', value: SUMMARY.total_settlements, sub: `${matchRate}% match rate`, cls: 'emerald' },
    { label: 'Discrepancies', value: SUMMARY.total_discrepancies, sub: 'Across 4 categories', cls: 'rose' },
    { label: 'Tolerance', value: '₹' + SUMMARY.amount_tolerance, sub: 'Per-transaction limit', cls: 'amber' },
    { label: 'Settlement Window', value: SUMMARY.settlement_delay_assumed, sub: 'Next business day', cls: 'purple' },
    { label: 'Rounding Drift', value: '₹' + ROUNDING.aggregate_delta.toFixed(2), sub: `${ROUNDING.affected_txns.length} transactions affected`, cls: 'cyan' }
  ];

  container.innerHTML = cards.map((c, i) => `
    <div class="stat-card ${c.cls} fade-up" style="animation-delay:${i * 0.07}s">
      <div class="stat-label">${c.label}</div>
      <div class="stat-value ${c.cls}">${c.value}</div>
      <div class="stat-sub">${c.sub}</div>
    </div>
  `).join('');
}

function renderDiscrepancyFilters() {
  const bar = $('#filter-bar');
  const types = ['ALL', ...Object.keys(SUMMARY.discrepancy_counts)];
  bar.innerHTML = types.map(t => {
    const label = t === 'ALL' ? 'All Types' : formatType(t);
    const count = t === 'ALL' ? SUMMARY.total_discrepancies : SUMMARY.discrepancy_counts[t];
    return `<button class="filter-btn ${t === 'ALL' ? 'active' : ''}" data-type="${t}">${label} (${count})</button>`;
  }).join('');

  bar.addEventListener('click', (e) => {
    if (!e.target.classList.contains('filter-btn')) return;
    $$('.filter-btn').forEach(b => b.classList.remove('active'));
    e.target.classList.add('active');
    renderDiscrepancyCards(e.target.dataset.type);
  });
}

function formatType(t) {
  return t.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()).replace(/\bTxn\b/i, 'Txn');
}

function badgeClass(type) {
  const map = {
    TIMING_MISMATCH: 'timing',
    DUPLICATE_TRANSACTION: 'duplicate',
    ORPHAN_REFUND: 'orphan',
    AMOUNT_MISMATCH: 'rounding',
    MISSING_SETTLEMENT: 'missing'
  };
  return map[type] || 'missing';
}

function renderDiscrepancyCards(filter = 'ALL') {
  const container = $('#disc-cards');
  const items = filter === 'ALL' ? DISCREPANCIES : DISCREPANCIES.filter(d => d.discrepancy_type === filter);

  if (items.length === 0) {
    container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:2rem;">No discrepancies for this filter.</p>';
    return;
  }

  container.innerHTML = items.map((d, i) => {
    const meta = [];
    if (d.txn_id) meta.push(`ID: ${d.txn_id}`);
    if (d.transaction_amount) meta.push(`Amount: ₹${d.transaction_amount}`);
    if (d.settled_amount) meta.push(`Settled: ₹${d.settled_amount}`);
    if (d.txn_timestamp) meta.push(`Date: ${d.txn_timestamp.split(' ')[0]}`);

    return `
      <div class="disc-card fade-up" style="animation-delay:${i * 0.08}s">
        <span class="badge ${badgeClass(d.discrepancy_type)}">${formatType(d.discrepancy_type)}</span>
        <h4>${d.txn_id}</h4>
        <p>${d.description}</p>
        <div class="disc-meta">${meta.map(m => `<span>${m}</span>`).join('')}</div>
      </div>
    `;
  }).join('');
}

function renderBarChart() {
  const container = $('#bar-chart');
  const counts = SUMMARY.discrepancy_counts;
  const max = Math.max(...Object.values(counts), 1);
  const colors = ['amber', 'rose', 'blue', 'purple'];

  container.innerHTML = Object.entries(counts).map(([type, count], i) => {
    const pct = Math.max((count / max) * 100, 15);
    return `
      <div class="bar-row fade-up" style="animation-delay:${i * 0.1}s">
        <span class="bar-label">${formatType(type)}</span>
        <div class="bar-track">
          <div class="bar-fill ${colors[i % colors.length]}" style="width:${pct}%">${count}</div>
        </div>
      </div>
    `;
  }).join('');
}

function renderDonut() {
  const container = $('#donut-chart');
  const counts = SUMMARY.discrepancy_counts;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const colors = ['#f59e0b', '#f43f5e', '#3b82f6', '#8b5cf6'];
  const entries = Object.entries(counts);

  // Build conic gradient
  let gradientParts = [];
  let cumulative = 0;
  entries.forEach(([, count], i) => {
    const pct = (count / total) * 100;
    gradientParts.push(`${colors[i]} ${cumulative}% ${cumulative + pct}%`);
    cumulative += pct;
  });

  const legendHtml = entries.map(([type, count], i) =>
    `<div class="legend-item"><div class="legend-dot" style="background:${colors[i]}"></div>${formatType(type)}: ${count}</div>`
  ).join('');

  container.innerHTML = `
    <div class="donut-wrap">
      <div class="donut" style="background:conic-gradient(${gradientParts.join(',')})">
        <div class="donut-center">
          <div class="num">${total}</div>
          <div class="lbl">Total</div>
        </div>
      </div>
      <div class="legend">${legendHtml}</div>
    </div>
  `;
}

function renderRounding() {
  const container = $('#rounding-detail');
  container.innerHTML = `
    <div class="rounding-box">
      <h4>⚖️ Rounding Analysis (ROUND_HALF_UP vs ROUND_HALF_EVEN)</h4>
      <div class="rounding-row"><span class="label">Platform Total</span><span class="val">₹${ROUNDING.platform_total.toFixed(2)}</span></div>
      <div class="rounding-row"><span class="label">Bank Total</span><span class="val">₹${ROUNDING.bank_total.toFixed(2)}</span></div>
      <div class="rounding-row"><span class="label">Aggregate Drift</span><span class="val delta">₹${ROUNDING.aggregate_delta.toFixed(2)}</span></div>
      <div class="rounding-row"><span class="label">Affected Transactions</span><span class="val">${ROUNDING.affected_txns.length}</span></div>
      <div class="rounding-row"><span class="label">Transaction IDs</span><span class="val mono">${ROUNDING.affected_txns.join(', ')}</span></div>
    </div>
  `;
}

function renderTable() {
  const container = $('#disc-table');
  const rows = DISCREPANCIES.map(d => `
    <tr>
      <td class="mono">${d.txn_id}</td>
      <td><span class="badge ${badgeClass(d.discrepancy_type)}">${formatType(d.discrepancy_type)}</span></td>
      <td>${d.transaction_amount ? '₹' + d.transaction_amount : '—'}</td>
      <td>${d.settled_amount ? '₹' + d.settled_amount : '—'}</td>
      <td>${d.txn_timestamp || '—'}</td>
      <td style="max-width:300px;font-size:0.75rem;color:var(--text-muted)">${d.description}</td>
    </tr>
  `).join('');

  container.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Txn ID</th><th>Type</th><th>Txn Amount</th><th>Settled</th><th>Timestamp</th><th>Description</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function renderAssumptions() {
  const container = $('#assumptions');
  container.innerHTML = ASSUMPTIONS.map(a => `
    <div class="assumption-item">
      <h5>${a.title}</h5>
      <p>${a.text}</p>
    </div>
  `).join('');
}

// ─── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadData();

  // Parallax background
  document.addEventListener('mousemove', (e) => {
    const x = (e.clientX / window.innerWidth) * 100;
    const y = (e.clientY / window.innerHeight) * 100;
    document.querySelector('.bg-grid').style.setProperty('--x', x + '%');
    document.querySelector('.bg-grid').style.setProperty('--y', y + '%');
  });
});
