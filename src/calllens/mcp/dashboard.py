"""
Live observability dashboard — no auth required (read-only aggregate metrics).

Served at GET /dashboard  →  HTML page with Chart.js
Served at GET /api/metrics → JSON (used by the HTML page and external tooling)

All queries are tenant-scoped to DEFAULT_TENANT_ID.
"""

from __future__ import annotations

import uuid
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from calllens.config import settings
from calllens.db import tenant_conn

router = APIRouter()

# Resolved lazily so settings are fully loaded before we read them
def _tenant_id() -> uuid.UUID:
    return uuid.UUID(str(settings.default_tenant_id))


@router.get("/api/metrics", response_class=JSONResponse)
async def get_metrics():
    tid = _tenant_id()
    async with tenant_conn(tid) as conn:
        call_count = await conn.fetchval(
            "SELECT COUNT(*) FROM calls WHERE tenant_id=$1", tid
        )
        insight_count = await conn.fetchval(
            "SELECT COUNT(*) FROM insights WHERE tenant_id=$1", tid
        )
        account_count = await conn.fetchval(
            "SELECT COUNT(*) FROM accounts WHERE tenant_id=$1", tid
        )

        # Sentiment distribution
        sentiment_rows = await conn.fetch(
            """SELECT overall_sentiment, COUNT(*)::int AS cnt
               FROM call_summaries cs JOIN calls c ON c.id=cs.call_id
               WHERE c.tenant_id=$1 GROUP BY 1 ORDER BY 2 DESC""",
            tid,
        )

        # Call type distribution
        type_rows = await conn.fetch(
            """SELECT call_type, COUNT(*)::int AS cnt
               FROM call_classifications cc JOIN calls c ON c.id=cc.call_id
               WHERE c.tenant_id=$1 GROUP BY 1 ORDER BY 2 DESC""",
            tid,
        )

        # Top topics
        topic_rows = await conn.fetch(
            """SELECT unnest(topics) AS topic, COUNT(*)::int AS freq
               FROM call_summaries cs JOIN calls c ON c.id=cs.call_id
               WHERE c.tenant_id=$1 GROUP BY 1 ORDER BY 2 DESC LIMIT 12""",
            tid,
        )

        # Insights by persona
        persona_rows = await conn.fetch(
            """SELECT persona::text, COUNT(*)::int AS cnt
               FROM insights WHERE tenant_id=$1 GROUP BY 1 ORDER BY 1""",
            tid,
        )

        # Insight severity breakdown
        severity_rows = await conn.fetch(
            """SELECT severity, COUNT(*)::int AS cnt
               FROM insights WHERE tenant_id=$1 GROUP BY 1 ORDER BY 2 DESC""",
            tid,
        )

        # Account health (top 10 by call count)
        account_rows = await conn.fetch(
            """SELECT a.name,
                      COUNT(cc.call_id)::int AS calls,
                      AVG(cs.sentiment_score)::numeric(4,2) AS avg_sentiment
               FROM accounts a
               JOIN call_classifications cc ON cc.account_id=a.id
               JOIN calls c ON c.id=cc.call_id
               JOIN call_summaries cs ON cs.call_id=c.id
               WHERE a.tenant_id=$1
               GROUP BY a.name ORDER BY calls DESC LIMIT 10""",
            tid,
        )

    return {
        "summary": {
            "calls": int(call_count),
            "insights": int(insight_count),
            "accounts": int(account_count),
        },
        "sentiment": [{"label": r["overall_sentiment"], "count": r["cnt"]} for r in sentiment_rows],
        "call_types": [{"label": r["call_type"], "count": r["cnt"]} for r in type_rows],
        "topics": [{"topic": r["topic"], "freq": r["freq"]} for r in topic_rows],
        "personas": [{"persona": r["persona"], "count": r["cnt"]} for r in persona_rows],
        "severity": [{"severity": r["severity"], "count": r["cnt"]} for r in severity_rows],
        "accounts": [
            {
                "name": r["name"],
                "calls": r["calls"],
                "avg_sentiment": float(r["avg_sentiment"] or 0),
            }
            for r in account_rows
        ],
    }


_DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CallLens · Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3a;
    --text: #e2e8f0; --muted: #94a3b8; --accent: #4B7CF3;
    --green: #10b981; --red: #ef4444; --yellow: #f59e0b;
    --purple: #8b5cf6;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: system-ui, sans-serif; padding: 24px; }
  header { margin-bottom: 20px; }
  header h1 { font-size: 20px; font-weight: 700; }
  header p  { font-size: 12px; color: var(--muted); margin-top: 3px; }
  .kpis { display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
  .kpi  { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
           padding: 14px 18px; min-width: 120px; }
  .kpi .val { font-size: 28px; font-weight: 700; }
  .kpi .lbl { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .card.wide { grid-column: span 2; }
  .card h3 { font-size: 11px; font-weight: 600; color: var(--muted); text-transform: uppercase;
              letter-spacing: .06em; margin-bottom: 12px; }
  canvas { max-height: 200px !important; }
  table { width: 100%; border-collapse: collapse; font-size: 11px; }
  th { text-align:left; color:var(--muted); font-weight:600; padding:4px 8px;
       border-bottom:1px solid var(--border); }
  td { padding: 5px 8px; border-bottom: 1px solid var(--border); }
  .chip { display:inline-block; padding:2px 7px; border-radius:12px; font-size:10px; font-weight:600; }
  .chip-red  { background:#450a0a; color:#fca5a5; }
  .chip-yellow { background:#422006; color:#fde68a; }
  .chip-green { background:#052e16; color:#86efac; }
  footer { margin-top: 20px; font-size: 11px; color: var(--muted); text-align: center; }
  .refresh { float:right; background:var(--accent); color:#fff; border:none; border-radius:6px;
             padding:6px 14px; font-size:12px; cursor:pointer; }
</style>
</head>
<body>
<header>
  <h1>📊 CallLens &mdash; Observability Dashboard</h1>
  <p id="subtitle">Loading metrics…</p>
  <button class="refresh" onclick="load()">↻ Refresh</button>
</header>

<div class="kpis" id="kpis"></div>

<div class="grid">
  <div class="card"><h3>Sentiment Distribution</h3><canvas id="cSent"></canvas></div>
  <div class="card"><h3>Call Types</h3><canvas id="cType"></canvas></div>
  <div class="card"><h3>Insights by Persona</h3><canvas id="cPersona"></canvas></div>
  <div class="card wide"><h3>Top Topics</h3><canvas id="cTopics"></canvas></div>
  <div class="card"><h3>Account Health</h3><table id="tAccounts">
    <tr><th>Account</th><th>Calls</th><th>Sentiment</th></tr>
  </table></div>
</div>

<footer>CallLens · Aegis Cloud tenant · Data refreshed on load · <a href="/health" style="color:var(--accent)">health</a></footer>

<script>
const PAL = ['#4B7CF3','#10b981','#f59e0b','#ef4444','#8b5cf6','#06b6d4','#f97316','#64748b','#84cc16','#e879f9','#0ea5e9','#fb923c'];
let charts = {};

function destroyAll() { Object.values(charts).forEach(c => c.destroy()); charts = {}; }

function sentimentColor(label) {
  if (label.includes('negative')) return label.includes('very') ? '#991b1b' : '#ef4444';
  if (label.includes('positive')) return label.includes('very') ? '#166534' : '#10b981';
  return '#f59e0b';
}

function chip(score) {
  if (score < 3) return `<span class="chip chip-red">${score} ▼</span>`;
  if (score < 4) return `<span class="chip chip-yellow">${score} ~</span>`;
  return `<span class="chip chip-green">${score} ▲</span>`;
}

async function load() {
  const res = await fetch('/api/metrics');
  const d = await res.json();
  destroyAll();

  document.getElementById('subtitle').textContent =
    `Tenant: Aegis Cloud · ${new Date().toLocaleTimeString()}`;

  // KPIs
  const kpiDefs = [
    { val: d.summary.calls, lbl: 'Calls analysed' },
    { val: d.summary.insights, lbl: 'Insights generated' },
    { val: d.summary.accounts, lbl: 'Accounts tracked' },
    { val: d.personas.length, lbl: 'Personas served' },
  ];
  document.getElementById('kpis').innerHTML = kpiDefs
    .map(k => `<div class="kpi"><div class="val">${k.val}</div><div class="lbl">${k.lbl}</div></div>`)
    .join('');

  // Sentiment
  charts.sent = new Chart(document.getElementById('cSent'), {
    type: 'doughnut',
    data: {
      labels: d.sentiment.map(r => r.label),
      datasets: [{ data: d.sentiment.map(r => r.count),
                   backgroundColor: d.sentiment.map(r => sentimentColor(r.label)), borderWidth: 0 }]
    },
    options: { cutout: '55%', plugins: { legend: { position: 'right',
      labels: { color: '#94a3b8', font: { size: 10 }, boxWidth: 10 } } } }
  });

  // Call types
  charts.type = new Chart(document.getElementById('cType'), {
    type: 'doughnut',
    data: {
      labels: d.call_types.map(r => r.label),
      datasets: [{ data: d.call_types.map(r => r.count),
                   backgroundColor: ['#4B7CF3','#f59e0b','#10b981'], borderWidth: 0 }]
    },
    options: { cutout: '55%', plugins: { legend: { position: 'right',
      labels: { color: '#94a3b8', font: { size: 10 }, boxWidth: 10 } } } }
  });

  // Persona bar
  charts.persona = new Chart(document.getElementById('cPersona'), {
    type: 'bar',
    data: {
      labels: d.personas.map(r => r.persona.replace('_', ' ')),
      datasets: [{ data: d.personas.map(r => r.count),
                   backgroundColor: ['#8b5cf6','#4B7CF3','#10b981','#f59e0b'], borderRadius: 4 }]
    },
    options: { plugins: { legend: { display: false } },
               scales: { x: { ticks: { color:'#94a3b8', font:{size:10} } },
                         y: { beginAtZero: true, ticks: { color:'#94a3b8', font:{size:10} } } } }
  });

  // Topics
  charts.topics = new Chart(document.getElementById('cTopics'), {
    type: 'bar',
    data: {
      labels: d.topics.map(r => r.topic),
      datasets: [{ data: d.topics.map(r => r.freq),
                   backgroundColor: PAL, borderRadius: 3 }]
    },
    options: { indexAxis: 'y', plugins: { legend: { display: false } },
               scales: { x: { ticks: { color:'#94a3b8', font:{size:10} } },
                         y: { ticks: { color:'#94a3b8', font:{size:10} } } } }
  });

  // Accounts table
  const tbody = d.accounts.map(a =>
    `<tr><td>${a.name}</td><td>${a.calls}</td><td>${chip(a.avg_sentiment)}</td></tr>`
  ).join('');
  document.getElementById('tAccounts').innerHTML =
    '<tr><th>Account</th><th>Calls</th><th>Avg sentiment</th></tr>' + tbody;
}

load();
</script>
</body>
</html>
"""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(_DASHBOARD_HTML)
