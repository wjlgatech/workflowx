"""ROI Dashboard — generates HTML dashboards (static or live).

Two modes:
  generate_dashboard_html()      → static self-contained file (baked-in data)
  generate_live_dashboard_html() → JS-driven shell that fetches /api/data live
                                   (used with `workflowx serve`)
"""

from __future__ import annotations

import json
from typing import Any, Sequence

import structlog

from workflowx.models import (
    FrictionTrend,
    ReplacementOutcome,
    WorkflowPattern,
)
from workflowx.measurement import compute_roi_summary

logger = structlog.get_logger()


def generate_dashboard_html(
    trends: Sequence[FrictionTrend],
    patterns: Sequence[WorkflowPattern],
    outcomes: Sequence[ReplacementOutcome],
    hourly_rate: float = 75.0,
) -> str:
    """Generate a self-contained HTML dashboard with Chart.js.

    Returns a complete HTML string — no external dependencies at runtime
    (Chart.js is loaded from CDN but works offline if cached).
    """
    roi = compute_roi_summary(outcomes)
    weekly_usd = roi["total_weekly_savings_hours"] * hourly_rate
    cumul_usd = roi["total_cumulative_savings_hours"] * hourly_rate

    # Prepare chart data
    trend_labels = json.dumps([t.week_label for t in trends])
    trend_friction = json.dumps([round(t.high_friction_ratio * 100, 1) for t in trends])
    trend_minutes = json.dumps([round(t.total_minutes, 0) for t in trends])

    pattern_labels = json.dumps([p.intent[:25] for p in patterns[:8]])
    pattern_times = json.dumps([round(p.total_time_invested_minutes, 0) for p in patterns[:8]])

    outcome_labels = json.dumps([o["intent"][:20] for o in roi["outcomes"][:10]])
    outcome_before = json.dumps([o["before"] for o in roi["outcomes"][:10]])
    outcome_after = json.dumps([o["after"] for o in roi["outcomes"][:10]])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WorkflowX ROI Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0d1117;
    color: #c9d1d9;
    padding: 24px;
  }}
  h1 {{ color: #f0f6fc; font-size: 28px; margin-bottom: 4px; }}
  .subtitle {{ color: #8b949e; font-size: 14px; margin-bottom: 24px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .card {{
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 20px;
  }}
  .card-label {{ color: #8b949e; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }}
  .card-value {{ color: #f0f6fc; font-size: 32px; font-weight: 700; margin-top: 4px; }}
  .card-sub {{ color: #8b949e; font-size: 13px; margin-top: 2px; }}
  .positive {{ color: #3fb950; }}
  .negative {{ color: #f85149; }}
  .chart-container {{
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 16px;
  }}
  .chart-title {{ color: #f0f6fc; font-size: 16px; font-weight: 600; margin-bottom: 12px; }}
  .charts-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 768px) {{ .charts-row {{ grid-template-columns: 1fr; }} }}
  .footer {{ text-align: center; color: #484f58; font-size: 12px; margin-top: 32px; }}
  .footer a {{ color: #58a6ff; text-decoration: none; }}
</style>
</head>
<body>
<h1>WorkflowX ROI Dashboard</h1>
<p class="subtitle">Observe. Understand. Replace. Measure. &mdash; <em>Static snapshot</em> &mdash; run <code>workflowx serve</code> for live updates</p>

<div class="grid">
  <div class="card">
    <div class="card-label">Weekly Time Saved</div>
    <div class="card-value positive">{roi['total_weekly_savings_minutes']:.0f}<span style="font-size:16px"> min</span></div>
    <div class="card-sub">{roi['total_weekly_savings_hours']:.1f} hrs / ${weekly_usd:.0f} per week</div>
  </div>
  <div class="card">
    <div class="card-label">Cumulative Savings</div>
    <div class="card-value positive">{roi['total_cumulative_savings_hours']:.1f}<span style="font-size:16px"> hrs</span></div>
    <div class="card-sub">${cumul_usd:.0f} total value</div>
  </div>
  <div class="card">
    <div class="card-label">Replacements Tracked</div>
    <div class="card-value">{roi['total_outcomes']}</div>
    <div class="card-sub">{roi['adopted']} adopted, {roi['rejected']} rejected, {roi['measuring']} measuring</div>
  </div>
  <div class="card">
    <div class="card-label">Adoption Rate</div>
    <div class="card-value">{roi['adoption_rate']:.0%}</div>
    <div class="card-sub">of proposed replacements working</div>
  </div>
</div>

<div class="charts-row">
  <div class="chart-container">
    <div class="chart-title">Friction Ratio Over Time (%)</div>
    <canvas id="frictionChart"></canvas>
  </div>
  <div class="chart-container">
    <div class="chart-title">Time Invested by Pattern (min)</div>
    <canvas id="patternChart"></canvas>
  </div>
</div>

<div class="chart-container">
  <div class="chart-title">Before vs After Replacement (min/week)</div>
  <canvas id="roiChart"></canvas>
</div>

<div class="footer">
  Generated by <a href="https://github.com/wjlgatech/workflowx">WorkflowX</a> &mdash;
  Local-first workflow intelligence
</div>

<script>
Chart.defaults.color = '#8b949e';
Chart.defaults.borderColor = '#30363d';

// Friction trend line chart
new Chart(document.getElementById('frictionChart'), {{
  type: 'line',
  data: {{
    labels: {trend_labels},
    datasets: [{{
      label: 'High Friction %',
      data: {trend_friction},
      borderColor: '#f85149',
      backgroundColor: 'rgba(248,81,73,0.1)',
      fill: true,
      tension: 0.3,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      y: {{ beginAtZero: true, max: 100, ticks: {{ callback: v => v+'%' }} }}
    }}
  }}
}});

// Pattern bar chart
new Chart(document.getElementById('patternChart'), {{
  type: 'bar',
  data: {{
    labels: {pattern_labels},
    datasets: [{{
      label: 'Minutes',
      data: {pattern_times},
      backgroundColor: '#58a6ff',
      borderRadius: 4,
    }}]
  }},
  options: {{
    responsive: true,
    indexAxis: 'y',
    plugins: {{ legend: {{ display: false }} }},
  }}
}});

// Before/after grouped bar chart
new Chart(document.getElementById('roiChart'), {{
  type: 'bar',
  data: {{
    labels: {outcome_labels},
    datasets: [
      {{
        label: 'Before (min/wk)',
        data: {outcome_before},
        backgroundColor: '#f85149',
        borderRadius: 4,
      }},
      {{
        label: 'After (min/wk)',
        data: {outcome_after},
        backgroundColor: '#3fb950',
        borderRadius: 4,
      }}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ position: 'top' }} }},
  }}
}});
</script>
</body>
</html>"""


def generate_live_dashboard_html() -> str:
    """Generate a live dashboard shell — all data fetched from /api/data.

    Used with `workflowx serve`. The page calls /api/data on load and
    whenever the user clicks the Update button.
    """
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WorkflowX Live Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0d1117;
    color: #c9d1d9;
    padding: 24px;
  }
  h1 { color: #f0f6fc; font-size: 28px; margin-bottom: 4px; }
  .subtitle { color: #8b949e; font-size: 14px; margin-bottom: 16px; }
  .toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 24px; }
  #update-btn {
    background: #21262d;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 13px;
    cursor: pointer;
    transition: background 0.15s;
  }
  #update-btn:hover { background: #30363d; }
  #update-btn:disabled { opacity: 0.5; cursor: default; }
  #status-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: #3fb950; display: inline-block; margin-right: 6px;
  }
  #status-dot.loading { background: #d29922; animation: pulse 1s infinite; }
  #status-dot.error { background: #f85149; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
  #last-updated { color: #484f58; font-size: 12px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 20px;
  }
  .card-label { color: #8b949e; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
  .card-value { color: #f0f6fc; font-size: 32px; font-weight: 700; margin-top: 4px; }
  .card-sub { color: #8b949e; font-size: 13px; margin-top: 2px; }
  .positive { color: #3fb950; }
  .chart-container {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 16px;
  }
  .chart-title { color: #f0f6fc; font-size: 16px; font-weight: 600; margin-bottom: 12px; }
  .charts-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media (max-width: 768px) { .charts-row { grid-template-columns: 1fr; } }
  .footer { text-align: center; color: #484f58; font-size: 12px; margin-top: 32px; }
  .footer a { color: #58a6ff; text-decoration: none; }
</style>
</head>
<body>
<h1>WorkflowX ROI Dashboard</h1>
<p class="subtitle">Observe. Understand. Replace. Measure.</p>

<div class="toolbar">
  <button id="update-btn" onclick="refreshData()">&#8635; Update</button>
  <span>
    <span id="status-dot" class="loading"></span>
    <span id="last-updated">Loading...</span>
  </span>
</div>

<div class="grid">
  <div class="card">
    <div class="card-label">Weekly Time Saved</div>
    <div class="card-value positive" id="kpi-weekly-min">--</div>
    <div class="card-sub" id="kpi-weekly-sub">--</div>
  </div>
  <div class="card">
    <div class="card-label">Cumulative Savings</div>
    <div class="card-value positive" id="kpi-cumul-hrs">--</div>
    <div class="card-sub" id="kpi-cumul-sub">--</div>
  </div>
  <div class="card">
    <div class="card-label">Replacements Tracked</div>
    <div class="card-value" id="kpi-total">--</div>
    <div class="card-sub" id="kpi-breakdown">--</div>
  </div>
  <div class="card">
    <div class="card-label">Adoption Rate</div>
    <div class="card-value" id="kpi-adoption">--</div>
    <div class="card-sub">of proposed replacements working</div>
  </div>
</div>

<div class="charts-row">
  <div class="chart-container">
    <div class="chart-title">Friction Ratio Over Time (%)</div>
    <canvas id="frictionChart"></canvas>
  </div>
  <div class="chart-container">
    <div class="chart-title">Time Invested by Pattern (min)</div>
    <canvas id="patternChart"></canvas>
  </div>
</div>

<div class="chart-container">
  <div class="chart-title">Before vs After Replacement (min/week)</div>
  <canvas id="roiChart"></canvas>
</div>

<div class="footer">
  <a href="https://github.com/wjlgatech/workflowx">WorkflowX</a> &mdash;
  Local-first workflow intelligence &mdash; live at <code>localhost</code>
</div>

<script>
Chart.defaults.color = '#8b949e';
Chart.defaults.borderColor = '#30363d';

let charts = {};

function destroyCharts() {
  Object.values(charts).forEach(c => c.destroy());
  charts = {};
}

function renderCharts(data) {
  destroyCharts();

  charts.friction = new Chart(document.getElementById('frictionChart'), {
    type: 'line',
    data: {
      labels: data.trend_labels,
      datasets: [{
        label: 'High Friction %',
        data: data.trend_friction,
        borderColor: '#f85149',
        backgroundColor: 'rgba(248,81,73,0.1)',
        fill: true,
        tension: 0.3,
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, max: 100, ticks: { callback: v => v + '%' } }
      }
    }
  });

  charts.pattern = new Chart(document.getElementById('patternChart'), {
    type: 'bar',
    data: {
      labels: data.pattern_labels,
      datasets: [{
        label: 'Minutes',
        data: data.pattern_times,
        backgroundColor: '#58a6ff',
        borderRadius: 4,
      }]
    },
    options: {
      responsive: true,
      indexAxis: 'y',
      plugins: { legend: { display: false } },
    }
  });

  charts.roi = new Chart(document.getElementById('roiChart'), {
    type: 'bar',
    data: {
      labels: data.outcome_labels,
      datasets: [
        {
          label: 'Before (min/wk)',
          data: data.outcome_before,
          backgroundColor: '#f85149',
          borderRadius: 4,
        },
        {
          label: 'After (min/wk)',
          data: data.outcome_after,
          backgroundColor: '#3fb950',
          borderRadius: 4,
        }
      ]
    },
    options: {
      responsive: true,
      plugins: { legend: { position: 'top' } },
    }
  });
}

function updateKPIs(kpis) {
  document.getElementById('kpi-weekly-min').innerHTML =
    Math.round(kpis.weekly_minutes) + '<span style="font-size:16px"> min</span>';
  document.getElementById('kpi-weekly-sub').textContent =
    kpis.weekly_hours.toFixed(1) + ' hrs / $' + Math.round(kpis.weekly_usd) + ' per week';

  document.getElementById('kpi-cumul-hrs').innerHTML =
    kpis.cumulative_hours.toFixed(1) + '<span style="font-size:16px"> hrs</span>';
  document.getElementById('kpi-cumul-sub').textContent =
    '$' + Math.round(kpis.cumulative_usd) + ' total value';

  document.getElementById('kpi-total').textContent = kpis.total_outcomes;
  document.getElementById('kpi-breakdown').textContent =
    kpis.adopted + ' adopted, ' + kpis.rejected + ' rejected, ' + kpis.measuring + ' measuring';

  document.getElementById('kpi-adoption').textContent =
    Math.round(kpis.adoption_rate * 100) + '%';
}

async function refreshData() {
  const btn = document.getElementById('update-btn');
  const dot = document.getElementById('status-dot');
  const ts = document.getElementById('last-updated');

  btn.disabled = true;
  dot.className = 'loading';
  ts.textContent = 'Updating...';

  try {
    const resp = await fetch('/api/data');
    if (!resp.ok) throw new Error('Server returned ' + resp.status);
    const data = await resp.json();
    updateKPIs(data.kpis);
    renderCharts(data);
    dot.className = '';
    ts.textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch (err) {
    dot.className = 'error';
    ts.textContent = 'Failed: ' + err.message;
  } finally {
    btn.disabled = false;
  }
}

refreshData();
</script>
</body>
</html>"""
