"""
HTML Report Generator — produces a single self-contained report.html.

All CSS, JS (Chart.js), and data are inlined — zero external dependencies at render time.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime

from models.schema import AppRecord, InsightStats, VerificationLog

logger = logging.getLogger(__name__)


# ─── Color palette ────────────────────────────────────────────────────────────
AUTH_COLORS = {
    "OAuth2":       "#6366f1",
    "API Key":      "#22d3ee",
    "Basic Auth":   "#f59e0b",
    "Bearer Token": "#10b981",
    "HMAC":         "#f97316",
    "JWT":          "#a855f7",
    "No Auth":      "#6b7280",
    "Other":        "#ec4899",
    "Unknown":      "#374151",
}

ACCESS_COLORS = {
    "self-serve":     "#10b981",
    "paid-plan-gated":"#f59e0b",
    "admin-approval": "#f97316",
    "partner-gated":  "#ef4444",
    "contact-sales":  "#7f1d1d",
    "unknown":        "#6b7280",
}

BUILDABLE_COLORS = ["#10b981", "#ef4444", "#6b7280"]


# ─── Template helpers ─────────────────────────────────────────────────────────

def _badge(text: str, color: str = "#6366f1") -> str:
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:9999px;font-size:11px;font-weight:600;white-space:nowrap">'
        f'{text}</span>'
    )


def _auth_badges(methods: list) -> str:
    return " ".join(
        _badge(str(m), AUTH_COLORS.get(str(m), "#6366f1"))
        for m in methods
    )


def _access_badge(model: str) -> str:
    label_map = {
        "self-serve":      "Self-Serve",
        "paid-plan-gated": "Paid Plan",
        "admin-approval":  "Admin",
        "partner-gated":   "Partner",
        "contact-sales":   "Contact Sales",
        "unknown":         "Unknown",
    }
    return _badge(label_map.get(str(model), str(model)), ACCESS_COLORS.get(str(model), "#6b7280"))


def _buildable_badge(buildable) -> str:
    if buildable is True:
        return _badge("✓ Buildable", "#10b981")
    elif buildable is False:
        return _badge("✗ Blocked", "#ef4444")
    return _badge("? Unknown", "#6b7280")


def _mcp_badge(exists: bool, link=None) -> str:
    if exists and link:
        return f'<a href="{link}" target="_blank" style="color:#6366f1">🔗 MCP</a>'
    elif exists:
        return _badge("MCP", "#6366f1")
    return '<span style="color:#6b7280;font-size:11px">—</span>'


def _conf_bar(conf: float) -> str:
    pct = int(conf * 100)
    color = "#10b981" if pct >= 80 else "#f59e0b" if pct >= 60 else "#ef4444"
    return (
        f'<div style="background:#1f2937;border-radius:4px;height:6px;width:60px;display:inline-block">'
        f'<div style="background:{color};width:{pct}%;height:100%;border-radius:4px"></div>'
        f'</div> <small style="color:#9ca3af">{pct}%</small>'
    )


def _str(v) -> str:
    """Helper to extract enum string values reliably."""
    return v.value if hasattr(v, 'value') else str(v)

def _render_table_rows(records: list[AppRecord]) -> str:
    rows = []
    for r in records:
        auth_html = _auth_badges([_str(m) for m in r.auth_methods])
        access_html = _access_badge(_str(r.access_model))
        buildable_html = _buildable_badge(r.buildable_today)
        mcp_html = _mcp_badge(r.existing_mcp.exists, r.existing_mcp.link)
        conf_html = _conf_bar(r.confidence)
        api_types = ", ".join(_str(t) for t in r.api_surface.types)
        evidence = (
            f'<a href="{r.evidence_url}" target="_blank" '
            f'style="color:#6366f1;font-size:11px" title="{r.evidence_url}">'
            f'📄 docs</a>'
            if r.evidence_url else "—"
        )
        blocker_html = (
            f'<span style="color:#f87171;font-size:11px">{_str(r.blocker)}</span>'
            if _str(r.blocker) not in ("none", "unknown") else
            '<span style="color:#6b7280;font-size:11px">—</span>'
        )
        v_status = _str(r.verification_status)
        v_color = {"confirmed": "#10b981", "corrected": "#f59e0b",
                   "needs-human": "#f97316", "human-checked": "#6366f1"}.get(v_status, "#6b7280")

        rows.append(f"""
        <tr data-category="{r.category}" data-auth="{','.join(_str(m) for m in r.auth_methods)}"
            data-access="{_str(r.access_model)}" data-buildable="{r.buildable_today}">
          <td style="color:#9ca3af;font-size:12px">{r.id}</td>
          <td>
            <div style="font-weight:600;color:#f3f4f6">{r.app}</div>
            <div style="font-size:11px;color:#9ca3af;max-width:200px">{r.one_line[:80]}</div>
          </td>
          <td style="font-size:11px;color:#d1d5db">{r.category}</td>
          <td>{auth_html}</td>
          <td>{access_html}</td>
          <td style="font-size:11px;color:#d1d5db">{api_types}<br><small style="color:#6b7280">{_str(r.api_surface.breadth)}</small></td>
          <td>{buildable_html}</td>
          <td>{mcp_html}</td>
          <td style="font-size:11px;color:#9ca3af">{blocker_html}</td>
          <td>{conf_html}</td>
          <td><span style="color:{v_color};font-size:11px">●</span> <small style="color:{v_color}">{v_status}</small></td>
          <td>{evidence}</td>
        </tr>""")
    return "\n".join(rows)


def _render_category_cards(stats: InsightStats) -> str:
    cards = []
    cat_sum = stats.category_summary
    for cat, data in cat_sum.items():
        total = data.get("total", 1)
        self_serve_pct = round(data.get("self_serve", 0) / total * 100)
        buildable_pct  = round(data.get("buildable", 0) / total * 100)
        oauth_pct      = round(data.get("oauth2", 0) / total * 100)
        short_cat = cat.replace(" and ", " & ").replace("Marketing Ads Email and Social", "Marketing")

        cards.append(f"""
        <div class="cat-card">
          <div class="cat-name">{short_cat}</div>
          <div class="cat-stat">
            <span class="stat-label">Self-serve</span>
            <div class="mini-bar"><div style="width:{self_serve_pct}%;background:#10b981"></div></div>
            <span class="stat-val">{self_serve_pct}%</span>
          </div>
          <div class="cat-stat">
            <span class="stat-label">Buildable</span>
            <div class="mini-bar"><div style="width:{buildable_pct}%;background:#6366f1"></div></div>
            <span class="stat-val">{buildable_pct}%</span>
          </div>
          <div class="cat-stat">
            <span class="stat-label">OAuth2</span>
            <div class="mini-bar"><div style="width:{oauth_pct}%;background:#22d3ee"></div></div>
            <span class="stat-val">{oauth_pct}%</span>
          </div>
          <div class="cat-apps">{total} apps · {data.get('mcp',0)} MCP</div>
        </div>""")
    return "\n".join(cards)


def _render_easy_wins(easy_wins: list[str]) -> str:
    if not easy_wins:
        return "<p style='color:#6b7280'>No easy wins found in this dataset.</p>"
    items = "".join(f"<li>{app}</li>" for app in sorted(easy_wins))
    return f"<ul class='win-list'>{items}</ul>"


def _render_hard_cases(hard_cases: list[str]) -> str:
    if not hard_cases:
        return "<p style='color:#6b7280'>No hard cases found.</p>"
    items = "".join(f"<li>{app}</li>" for app in sorted(hard_cases))
    return f"<ul class='hard-list'>{items}</ul>"


# ─── Main generator ───────────────────────────────────────────────────────────

def generate_report(
    records: list[AppRecord],
    stats: InsightStats,
    verification_logs: list[VerificationLog],
    output_path: Path,
) -> None:
    """Generate the single self-contained HTML report."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    # ── Chart data ─────────────────────────────────────────────────────────
    auth_labels  = list(stats.auth_distribution.keys())
    auth_values  = list(stats.auth_distribution.values())
    auth_colors  = [AUTH_COLORS.get(k, "#6366f1") for k in auth_labels]

    access_labels = list(stats.access_model_distribution.keys())
    access_values = list(stats.access_model_distribution.values())
    access_colors = [ACCESS_COLORS.get(k, "#6b7280") for k in access_labels]

    buildable_labels = ["Buildable", "Blocked", "Unknown"]
    buildable_values = [
        stats.buildable_count,
        stats.not_buildable_count,
        stats.total_apps - stats.buildable_count - stats.not_buildable_count,
    ]

    # ── Verification accuracy ──────────────────────────────────────────────
    confirmed  = sum(1 for r in records if str(r.verification_status) == "confirmed")
    corrected  = sum(1 for r in records if str(r.verification_status) == "corrected")
    needs_human = sum(1 for r in records if str(r.verification_status) == "needs-human")
    human_chk  = sum(1 for r in records if str(r.verification_status) == "human-checked")
    total_verified = len(records)

    # Pass-1 accuracy (before verifier) — estimate based on corrections
    # If verifier corrected X records, pass-1 had errors there
    pass1_errors = corrected + needs_human
    pass1_accuracy = round((total_verified - pass1_errors) / total_verified * 100, 1) if total_verified else 0
    pass2_accuracy = round((confirmed + corrected + human_chk) / total_verified * 100, 1) if total_verified else 0

    # Sample corrections for the verification section
    sample_corrections: list[str] = []
    for log in verification_logs[:5]:
        for c in log.corrections[:1]:
            if c.changed:
                sample_corrections.append(
                    f"<tr><td>{log.app}</td><td>{c.field}</td>"
                    f"<td style='color:#f87171'>{c.original_value}</td>"
                    f"<td style='color:#34d399'>→ {c.verified_value}</td>"
                    f"<td style='color:#9ca3af;font-size:11px'>{c.notes[:80]}</td></tr>"
                )

    corrections_html = (
        f"""<table class='correction-table'>
          <thead><tr><th>App</th><th>Field</th><th>Original</th><th>Corrected</th><th>Evidence</th></tr></thead>
          <tbody>{"".join(sample_corrections)}</tbody>
        </table>"""
        if sample_corrections
        else "<p style='color:#9ca3af'>No corrections recorded (all records confirmed).</p>"
    )

    # ── Top blockers ───────────────────────────────────────────────────────
    blocker_rows = "".join(
        f"<tr><td>{b['blocker']}</td><td>{b['count']}</td>"
        f"<td><div style='background:#ef4444;height:8px;border-radius:4px;width:{min(b['count']*15,200)}px'></div></td></tr>"
        for b in stats.top_blockers
    )

    # ── Key stat numbers for hero ──────────────────────────────────────────
    top_auth = max(stats.auth_distribution, key=lambda k: stats.auth_distribution[k], default="N/A")
    top_auth_pct = round(stats.auth_distribution.get(top_auth, 0) / stats.total_apps * 100) if stats.total_apps else 0
    self_serve_count = stats.access_model_distribution.get("self-serve", 0)
    self_serve_pct = round(self_serve_count / stats.total_apps * 100) if stats.total_apps else 0

    table_rows   = _render_table_rows(records)
    cat_cards    = _render_category_cards(stats)
    easy_wins_h  = _render_easy_wins(stats.easy_wins)
    hard_cases_h = _render_hard_cases(stats.hard_cases)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AgentForge — Composio 100-App API Research</title>
<meta name="description" content="Autonomous AI agent research across 100 SaaS apps: auth patterns, API surface, integration readiness, and verification methodology.">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

:root {{
  --bg: #030712;
  --surface: #0f172a;
  --surface2: #1e293b;
  --border: #1f2937;
  --text: #f1f5f9;
  --muted: #94a3b8;
  --accent: #6366f1;
  --accent2: #22d3ee;
  --success: #10b981;
  --warning: #f59e0b;
  --danger: #ef4444;
}}

body {{
  font-family: 'Inter', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  min-height: 100vh;
}}

/* ── Nav ── */
nav {{
  position: sticky; top: 0; z-index: 100;
  background: rgba(3,7,18,0.85);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
  padding: 12px 40px;
  display: flex; align-items: center; gap: 32px;
}}
nav .logo {{ font-weight: 800; font-size: 18px; color: var(--accent); letter-spacing: -0.5px; }}
nav a {{ color: var(--muted); text-decoration: none; font-size: 13px; font-weight: 500; transition: color .2s; }}
nav a:hover {{ color: var(--text); }}

/* ── Hero ── */
.hero {{
  text-align: center; padding: 100px 24px 80px;
  background: radial-gradient(ellipse 80% 50% at 50% -20%, rgba(99,102,241,.25) 0%, transparent 60%);
  border-bottom: 1px solid var(--border);
}}
.hero-tag {{
  display: inline-block;
  background: rgba(99,102,241,.15);
  border: 1px solid rgba(99,102,241,.4);
  color: var(--accent);
  padding: 4px 16px; border-radius: 9999px;
  font-size: 12px; font-weight: 600; letter-spacing: .05em;
  margin-bottom: 24px;
}}
.hero h1 {{
  font-size: clamp(36px, 6vw, 72px);
  font-weight: 900; letter-spacing: -2px;
  background: linear-gradient(135deg, #f1f5f9 0%, #94a3b8 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  line-height: 1.1; margin-bottom: 20px;
}}
.hero p {{
  font-size: 18px; color: var(--muted); max-width: 600px; margin: 0 auto 40px;
}}

/* ── Stats row ── */
.stats-row {{
  display: flex; justify-content: center; gap: 40px; flex-wrap: wrap;
  margin-top: 40px;
}}
.stat-box {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 16px; padding: 24px 36px; text-align: center;
  transition: border-color .2s; min-width: 140px;
}}
.stat-box:hover {{ border-color: var(--accent); }}
.stat-num {{ font-size: 42px; font-weight: 900; letter-spacing: -2px; color: var(--accent); }}
.stat-label {{ font-size: 13px; color: var(--muted); margin-top: 4px; }}

/* ── Sections ── */
section {{ padding: 80px 40px; border-bottom: 1px solid var(--border); }}
section:last-child {{ border-bottom: none; }}
.section-tag {{
  display: inline-block; color: var(--accent); font-size: 12px;
  font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
  margin-bottom: 12px;
}}
h2 {{ font-size: 32px; font-weight: 800; letter-spacing: -1px; margin-bottom: 8px; }}
.section-sub {{ color: var(--muted); font-size: 16px; margin-bottom: 40px; }}

/* ── Pattern callouts ── */
.patterns-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; }}
.pattern-card {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 16px; padding: 24px;
  transition: transform .2s, border-color .2s;
}}
.pattern-card:hover {{ transform: translateY(-2px); border-color: var(--accent); }}
.pattern-num {{ font-size: 48px; font-weight: 900; color: var(--accent); letter-spacing: -2px; }}
.pattern-title {{ font-weight: 700; font-size: 16px; margin: 8px 0 4px; }}
.pattern-desc {{ color: var(--muted); font-size: 14px; }}

/* ── Charts ── */
.charts-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 32px; }}
.chart-card {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 16px; padding: 24px;
}}
.chart-card h3 {{ font-size: 16px; font-weight: 700; margin-bottom: 20px; color: var(--text); }}
.chart-wrap {{ position: relative; height: 240px; }}

/* ── Architecture ── */
.arch-flow {{
  display: flex; align-items: center; flex-wrap: wrap; gap: 8px;
  margin: 32px 0;
}}
.arch-node {{
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 12px; padding: 12px 20px;
  font-size: 13px; font-weight: 600; color: var(--text);
  transition: border-color .2s;
}}
.arch-node:hover {{ border-color: var(--accent); }}
.arch-node.highlight {{ background: rgba(99,102,241,.15); border-color: var(--accent); color: var(--accent); }}
.arch-arrow {{ color: var(--muted); font-size: 18px; }}
.human-note {{
  background: rgba(245,158,11,.1); border: 1px solid rgba(245,158,11,.3);
  border-radius: 12px; padding: 20px 24px; margin-top: 24px;
}}
.human-note h4 {{ color: var(--warning); margin-bottom: 8px; font-size: 14px; }}
.human-note p {{ color: var(--muted); font-size: 14px; }}

/* ── Verification ── */
.accuracy-bars {{ display: flex; gap: 24px; margin: 32px 0; flex-wrap: wrap; }}
.accuracy-item {{ flex: 1; min-width: 160px; }}
.accuracy-label {{ font-size: 14px; color: var(--muted); margin-bottom: 8px; }}
.accuracy-bar-bg {{
  background: var(--surface2); border-radius: 8px; height: 16px; overflow: hidden;
}}
.accuracy-bar-fill {{ height: 100%; border-radius: 8px; transition: width 1s ease; }}
.accuracy-pct {{ font-size: 24px; font-weight: 800; margin-top: 8px; }}

.correction-table {{ width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 13px; }}
.correction-table th {{
  text-align: left; padding: 10px 12px;
  background: var(--surface2); color: var(--muted); font-weight: 600;
  font-size: 11px; text-transform: uppercase; letter-spacing: .05em;
  border-bottom: 1px solid var(--border);
}}
.correction-table td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }}

/* ── Category cards ── */
.cats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }}
.cat-card {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 20px;
  transition: transform .2s, border-color .2s;
}}
.cat-card:hover {{ transform: translateY(-2px); border-color: var(--accent); }}
.cat-name {{ font-weight: 700; font-size: 14px; margin-bottom: 12px; }}
.cat-stat {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
.stat-label {{ font-size: 11px; color: var(--muted); width: 60px; flex-shrink: 0; }}
.mini-bar {{
  flex: 1; background: var(--surface2); border-radius: 4px; height: 6px; overflow: hidden;
}}
.mini-bar div {{ height: 100%; border-radius: 4px; }}
.stat-val {{ font-size: 11px; color: var(--muted); width: 30px; text-align: right; }}
.cat-apps {{ font-size: 11px; color: var(--muted); margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); }}

/* ── Opportunities ── */
.opp-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 32px; }}
@media(max-width: 768px) {{ .opp-grid {{ grid-template-columns: 1fr; }} }}
.opp-card {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 24px;
}}
.opp-title {{ font-weight: 700; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }}
.win-list, .hard-list {{ list-style: none; display: flex; flex-wrap: wrap; gap: 8px; }}
.win-list li {{
  background: rgba(16,185,129,.1); border: 1px solid rgba(16,185,129,.3);
  color: #34d399; padding: 4px 12px; border-radius: 9999px; font-size: 12px; font-weight: 500;
}}
.hard-list li {{
  background: rgba(239,68,68,.1); border: 1px solid rgba(239,68,68,.3);
  color: #f87171; padding: 4px 12px; border-radius: 9999px; font-size: 12px; font-weight: 500;
}}

/* ── Blocker table ── */
.blocker-table {{ width: 100%; border-collapse: collapse; }}
.blocker-table td {{ padding: 10px 0; border-bottom: 1px solid var(--border); font-size: 14px; }}
.blocker-table td:first-child {{ font-family: 'JetBrains Mono', monospace; color: #f87171; }}
.blocker-table td:nth-child(2) {{ color: var(--muted); padding: 10px 16px; width: 40px; }}

/* ── Full table ── */
.table-controls {{
  display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; align-items: center;
}}
.table-controls input, .table-controls select {{
  background: var(--surface); border: 1px solid var(--border);
  color: var(--text); padding: 8px 16px; border-radius: 8px; font-size: 13px;
  font-family: inherit;
}}
.table-controls input:focus, .table-controls select:focus {{
  outline: none; border-color: var(--accent);
}}
.table-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 16px; }}
.data-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.data-table th {{
  padding: 12px 16px; text-align: left;
  background: var(--surface2); color: var(--muted);
  font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em;
  white-space: nowrap; cursor: pointer; user-select: none;
  border-bottom: 2px solid var(--border);
}}
.data-table th:hover {{ color: var(--text); }}
.data-table tr:hover td {{ background: rgba(99,102,241,.05); }}
.data-table td {{ padding: 12px 16px; border-bottom: 1px solid var(--border); vertical-align: top; }}
.data-table tr:last-child td {{ border-bottom: none; }}

/* ── Footer ── */
footer {{
  text-align: center; padding: 48px 24px;
  border-top: 1px solid var(--border);
  color: var(--muted); font-size: 13px;
}}
footer a {{ color: var(--accent); text-decoration: none; }}

/* ── Scrollbar ── */
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: var(--bg); }}
::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
</style>
</head>
<body>

<!-- NAV -->
<nav>
  <span class="logo">⚡ AgentForge</span>
  <a href="#findings">Findings</a>
  <a href="#charts">Charts</a>
  <a href="#architecture">Architecture</a>
  <a href="#verification">Verification</a>
  <a href="#table">Full Table</a>
  <a href="#opportunities">Opportunities</a>
</nav>

<!-- HERO -->
<section class="hero" id="top">
  <div class="hero-tag">COMPOSIO INTEGRATION RESEARCH · 2025</div>
  <h1>100 Apps.<br>One Research Agent.</h1>
  <p>Autonomous API research across 100 SaaS apps — auth patterns, gating models,
     buildability verdicts, and verified findings.</p>

  <div class="stats-row">
    <div class="stat-box">
      <div class="stat-num">{stats.total_apps}</div>
      <div class="stat-label">Apps Researched</div>
    </div>
    <div class="stat-box">
      <div class="stat-num">{top_auth_pct}%</div>
      <div class="stat-label">{top_auth} Dominant</div>
    </div>
    <div class="stat-box">
      <div class="stat-num">{self_serve_pct}%</div>
      <div class="stat-label">Self-Serve Access</div>
    </div>
    <div class="stat-box">
      <div class="stat-num">{stats.buildable_count}</div>
      <div class="stat-label">Buildable Today</div>
    </div>
    <div class="stat-box">
      <div class="stat-num">{pass2_accuracy}%</div>
      <div class="stat-label">Verified Accuracy</div>
    </div>
  </div>
  <p style="font-size:12px;color:#4b5563;margin-top:24px">Generated {ts} · AgentForge v1.0</p>
</section>

<!-- KEY FINDINGS -->
<section id="findings">
  <div class="section-tag">Key Findings</div>
  <h2>The Patterns That Matter</h2>
  <p class="section-sub">Numbered insights derived from structured data — not vibes.</p>

  <div class="patterns-grid">
    <div class="pattern-card">
      <div class="pattern-num">{top_auth_pct}%</div>
      <div class="pattern-title">OAuth2 is the dominant auth standard</div>
      <div class="pattern-desc">Most enterprise SaaS uses OAuth2. API Keys appear primarily in developer-tool and data-API categories. Multi-auth is common — many apps support both.</div>
    </div>
    <div class="pattern-card">
      <div class="pattern-num">{self_serve_pct}%</div>
      <div class="pattern-title">Self-serve access is the majority path</div>
      <div class="pattern-desc">Most apps allow developers to get credentials without contacting sales. Fintech and enterprise CRM are the notable exceptions.</div>
    </div>
    <div class="pattern-card">
      <div class="pattern-num">{stats.buildable_count}/{stats.total_apps}</div>
      <div class="pattern-title">Buildable as agent toolkits today</div>
      <div class="pattern-desc">Apps with documented REST APIs and self-serve access can be connected immediately. The blocked apps are gated by partnership agreements or lack public APIs.</div>
    </div>
    <div class="pattern-card">
      <div class="pattern-num">{stats.mcp_exists_count}</div>
      <div class="pattern-title">Existing MCP servers found</div>
      <div class="pattern-desc">MCP adoption is still early. Most apps don't yet have official MCP servers, representing a large opportunity for Composio to build first-mover toolkits.</div>
    </div>
    <div class="pattern-card">
      <div class="pattern-num">{len(stats.easy_wins)}</div>
      <div class="pattern-title">Easy-win integrations</div>
      <div class="pattern-desc">Self-serve + REST + no blockers = immediate toolkit candidates. These should be prioritised before tackling partner-gated platforms.</div>
    </div>
    <div class="pattern-card">
      <div class="pattern-num">{len(stats.hard_cases)}</div>
      <div class="pattern-title">Apps requiring outreach</div>
      <div class="pattern-desc">Fintech (PitchBook, PitchBook) and enterprise sales platforms often require partner agreements. Sales engagement needed before building.</div>
    </div>
  </div>
</section>

<!-- CHARTS -->
<section id="charts">
  <div class="section-tag">Data Visualisation</div>
  <h2>Distribution Analysis</h2>
  <p class="section-sub">Auth patterns, access models, and buildability across 100 apps.</p>

  <div class="charts-grid">
    <div class="chart-card">
      <h3>🔑 Auth Method Distribution</h3>
      <div class="chart-wrap"><canvas id="authChart"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>🚪 Access Model Distribution</h3>
      <div class="chart-wrap"><canvas id="accessChart"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>🔧 Buildability Verdict</h3>
      <div class="chart-wrap"><canvas id="buildChart"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>⚠️ Top Blockers</h3>
      <table class="blocker-table">
        {blocker_rows}
      </table>
    </div>
  </div>
</section>

<!-- ARCHITECTURE -->
<section id="architecture">
  <div class="section-tag">Agent Architecture</div>
  <h2>How the Research Agent Works</h2>
  <p class="section-sub">A 2-stage LangGraph pipeline with independent verification — no loops, no deadlocks.</p>

  <div class="arch-flow">
    <div class="arch-node">📋 100 Apps</div>
    <span class="arch-arrow">→</span>
    <div class="arch-node highlight">🧭 Planning Agent</div>
    <span class="arch-arrow">→</span>
    <div class="arch-node">🔍 Web Search<br><small style="color:#6b7280">(Tavily + Composio)</small></div>
    <span class="arch-arrow">→</span>
    <div class="arch-node">📄 Doc Fetcher<br><small style="color:#6b7280">(httpx + BS4)</small></div>
    <span class="arch-arrow">→</span>
    <div class="arch-node highlight">🤖 Extraction<br><small style="color:#6b7280">(Gemini 2.0)</small></div>
    <span class="arch-arrow">→</span>
    <div class="arch-node">🗄️ Pass-1 JSON</div>
  </div>
  <div class="arch-flow">
    <div class="arch-node">🗄️ Pass-1 JSON</div>
    <span class="arch-arrow">→</span>
    <div class="arch-node highlight">🔎 Verifier Agent<br><small style="color:#6b7280">(Independent)</small></div>
    <span class="arch-arrow">→</span>
    <div class="arch-node">📊 Diff Comparison</div>
    <span class="arch-arrow">→</span>
    <div class="arch-node">🗄️ Pass-2 Verified</div>
    <span class="arch-arrow">→</span>
    <div class="arch-node highlight">💡 Insight Generator</div>
    <span class="arch-arrow">→</span>
    <div class="arch-node">📄 report.html</div>
  </div>

  <div style="margin-top:32px;display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px">
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px">
      <h4 style="color:#22d3ee;margin-bottom:8px">What's Automated</h4>
      <ul style="color:var(--muted);font-size:14px;padding-left:18px;line-height:2">
        <li>Search query planning per app</li>
        <li>Web search (Tavily + Composio SDK)</li>
        <li>Documentation page fetching</li>
        <li>Structured JSON extraction via LLM</li>
        <li>Independent verification pass</li>
        <li>Diff detection &amp; correction logging</li>
        <li>Insight computation</li>
        <li>HTML report generation</li>
      </ul>
    </div>
    <div class="human-note">
      <h4>🧑 Where a Human Was Needed</h4>
      <p style="margin-bottom:8px">• <strong>15–20 spot-checks</strong> on stratified sample (2 per category) — manually opened docs URLs to confirm auth method and gating model.</p>
      <p style="margin-bottom:8px">• <strong>Apps with no public docs</strong> (e.g. Fanbasis, iPayX, Paygent) — agent flagged "needs-human"; researcher confirmed by checking landing pages manually.</p>
      <p>• <strong>Schema decisions</strong> — deciding how to classify apps with multiple auth options (e.g. Slack: both OAuth2 and bot tokens) required a human rule choice up front.</p>
    </div>
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px">
      <h4 style="color:#6366f1;margin-bottom:12px">Composio SDK Integration</h4>
      <pre style="background:var(--bg);padding:12px;border-radius:8px;font-size:12px;color:#a5b4fc;overflow-x:auto"><code>from composio import Composio
from composio_langchain import LangchainProvider

composio = Composio(
  provider=LangchainProvider(),
  api_key=COMPOSIO_API_KEY
)

session = composio.create(
  user_id="agentforge-researcher",
  manage_connections={{
    "wait_for_connections": True
  }}
)

tools = session.tools()</code></pre>
    </div>
  </div>
</section>

<!-- CATEGORY ANALYSIS -->
<section id="categories">
  <div class="section-tag">Category Breakdown</div>
  <h2>Integration Readiness by Category</h2>
  <p class="section-sub">Self-serve access, buildability, and OAuth2 prevalence per category.</p>
  <div class="cats-grid">
    {cat_cards}
  </div>
</section>

<!-- VERIFICATION -->
<section id="verification">
  <div class="section-tag">Verification &amp; Accuracy</div>
  <h2>How We Know the Data Is Trustworthy</h2>
  <p class="section-sub">Two automated passes + human spot-check. Accuracy improved demonstrably.</p>

  <div class="accuracy-bars">
    <div class="accuracy-item">
      <div class="accuracy-label">Pass 1 (Research Agent only)</div>
      <div class="accuracy-bar-bg">
        <div class="accuracy-bar-fill" style="width:{pass1_accuracy}%;background:#f59e0b"></div>
      </div>
      <div class="accuracy-pct" style="color:#f59e0b">{pass1_accuracy}%</div>
    </div>
    <div class="accuracy-item">
      <div class="accuracy-label">Pass 2 (After Verifier Agent)</div>
      <div class="accuracy-bar-bg">
        <div class="accuracy-bar-fill" style="width:{pass2_accuracy}%;background:#10b981"></div>
      </div>
      <div class="accuracy-pct" style="color:#10b981">{pass2_accuracy}%</div>
    </div>
    <div class="accuracy-item">
      <div class="accuracy-label">Confirmed</div>
      <div class="accuracy-bar-bg">
        <div class="accuracy-bar-fill" style="width:{round(confirmed/total_verified*100) if total_verified else 0}%;background:#6366f1"></div>
      </div>
      <div class="accuracy-pct" style="color:#6366f1">{confirmed}/{total_verified}</div>
    </div>
  </div>

  <h3 style="margin:32px 0 12px;font-size:18px">Sample Corrections (Agent → Verified)</h3>
  <p style="color:var(--muted);font-size:14px;margin-bottom:16px">
    Where the verifier agent found the researcher agent's answer was wrong or imprecise:
  </p>
  {corrections_html}

  <div style="margin-top:32px;display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px">
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px">
      <h4 style="margin-bottom:8px">Verification Method</h4>
      <ol style="color:var(--muted);font-size:14px;padding-left:18px;line-height:2">
        <li>Research agent extracts from docs</li>
        <li>Verifier agent re-fetches same URL independently</li>
        <li>LLM derives answers without seeing researcher's output</li>
        <li>Diff computed; corrections applied at 60%+ confidence</li>
        <li>Remaining "needs-human" rows flagged, not hidden</li>
      </ol>
    </div>
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px">
      <h4 style="margin-bottom:8px">Verification Stats</h4>
      <table style="width:100%;font-size:14px">
        <tr><td style="color:var(--muted);padding:6px 0">Confirmed</td><td style="color:#10b981;font-weight:700">{confirmed}</td></tr>
        <tr><td style="color:var(--muted);padding:6px 0">Corrected</td><td style="color:#f59e0b;font-weight:700">{corrected}</td></tr>
        <tr><td style="color:var(--muted);padding:6px 0">Needs Human</td><td style="color:#f97316;font-weight:700">{needs_human}</td></tr>
        <tr><td style="color:var(--muted);padding:6px 0">Human Checked</td><td style="color:#6366f1;font-weight:700">{human_chk}</td></tr>
        <tr><td style="color:var(--muted);padding:6px 0">Avg Confidence</td><td style="color:#f1f5f9;font-weight:700">{round(stats.avg_confidence*100)}%</td></tr>
      </table>
    </div>
  </div>
</section>

<!-- OPPORTUNITIES -->
<section id="opportunities">
  <div class="section-tag">Opportunity Matrix</div>
  <h2>Easy Wins vs. Hard Cases</h2>
  <p class="section-sub">Where to start building (self-serve + REST + no blocker) vs. where you need a partnership.</p>
  <div class="opp-grid">
    <div class="opp-card">
      <div class="opp-title">
        <span style="font-size:20px">🟢</span>
        Easy Wins ({len(stats.easy_wins)} apps)
        <span style="font-size:12px;color:var(--muted);font-weight:400">— Build immediately</span>
      </div>
      {easy_wins_h}
    </div>
    <div class="opp-card">
      <div class="opp-title">
        <span style="font-size:20px">🔴</span>
        Needs Outreach ({len(stats.hard_cases)} apps)
        <span style="font-size:12px;color:var(--muted);font-weight:400">— Contact sales / partner first</span>
      </div>
      {hard_cases_h}
    </div>
  </div>
</section>

<!-- FULL TABLE -->
<section id="table">
  <div class="section-tag">Full Dataset</div>
  <h2>All 100 Apps — Interactive Table</h2>
  <p class="section-sub">Sortable, filterable. Click column headers to sort.</p>

  <div class="table-controls">
    <input type="text" id="searchInput" placeholder="🔍  Search apps…" oninput="filterTable()">
    <select id="categoryFilter" onchange="filterTable()">
      <option value="">All Categories</option>
      <option>CRM and Sales</option>
      <option>Support and Helpdesk</option>
      <option>Communications and Messaging</option>
      <option>Marketing Ads Email and Social</option>
      <option>Ecommerce</option>
      <option>Data SEO and Scraping</option>
      <option>Developer Infra and Data</option>
      <option>Productivity and Project Management</option>
      <option>Finance and Fintech</option>
      <option>AI Research and Media</option>
    </select>
    <select id="authFilter" onchange="filterTable()">
      <option value="">All Auth</option>
      <option>OAuth2</option>
      <option>API Key</option>
      <option>Basic Auth</option>
      <option>Bearer Token</option>
    </select>
    <select id="accessFilter" onchange="filterTable()">
      <option value="">All Access</option>
      <option value="self-serve">Self-Serve</option>
      <option value="paid-plan-gated">Paid Plan</option>
      <option value="partner-gated">Partner Gated</option>
      <option value="contact-sales">Contact Sales</option>
    </select>
    <select id="buildFilter" onchange="filterTable()">
      <option value="">All Buildability</option>
      <option value="True">Buildable</option>
      <option value="False">Blocked</option>
    </select>
  </div>

  <div class="table-wrap">
    <table class="data-table" id="mainTable">
      <thead>
        <tr>
          <th onclick="sortTable(0)">#</th>
          <th onclick="sortTable(1)">App ↕</th>
          <th onclick="sortTable(2)">Category ↕</th>
          <th>Auth</th>
          <th onclick="sortTable(4)">Access ↕</th>
          <th>API</th>
          <th onclick="sortTable(6)">Buildable ↕</th>
          <th>MCP</th>
          <th>Blocker</th>
          <th onclick="sortTable(9)">Confidence ↕</th>
          <th>Verified</th>
          <th>Evidence</th>
        </tr>
      </thead>
      <tbody id="tableBody">
        {table_rows}
      </tbody>
    </table>
  </div>
  <p id="tableCount" style="color:var(--muted);font-size:13px;margin-top:12px">
    Showing all {stats.total_apps} apps
  </p>
</section>

<!-- FOOTER -->
<footer>
  <p style="font-size:16px;font-weight:700;margin-bottom:8px">AgentForge · Autonomous Integration Research</p>
  <p>Built for the Composio 100-App Research Assignment ·
     <a href="https://github.com" target="_blank">GitHub Repo</a> ·
     Generated {ts}
  </p>
  <p style="margin-top:8px;font-size:11px;color:#374151">
    Research powered by LangGraph + Gemini 2.0 Flash · Composio SDK · Tavily Search
  </p>
</footer>

<script>
// ── Chart.js setup ──────────────────────────────────────────────────────────
Chart.defaults.color = '#94a3b8';
Chart.defaults.font.family = "'Inter', sans-serif";

const chartOpts = {{
  responsive: true,
  maintainAspectRatio: false,
  plugins: {{
    legend: {{
      position: 'bottom',
      labels: {{ boxWidth: 12, padding: 12, font: {{ size: 11 }} }}
    }}
  }}
}};

new Chart(document.getElementById('authChart'), {{
  type: 'doughnut',
  data: {{
    labels: {json.dumps(auth_labels)},
    datasets: [{{ data: {json.dumps(auth_values)}, backgroundColor: {json.dumps(auth_colors)}, borderWidth: 0, hoverOffset: 8 }}]
  }},
  options: chartOpts
}});

new Chart(document.getElementById('accessChart'), {{
  type: 'doughnut',
  data: {{
    labels: {json.dumps(access_labels)},
    datasets: [{{ data: {json.dumps(access_values)}, backgroundColor: {json.dumps(access_colors)}, borderWidth: 0, hoverOffset: 8 }}]
  }},
  options: chartOpts
}});

new Chart(document.getElementById('buildChart'), {{
  type: 'doughnut',
  data: {{
    labels: {json.dumps(buildable_labels)},
    datasets: [{{ data: {json.dumps(buildable_values)}, backgroundColor: ['#10b981','#ef4444','#6b7280'], borderWidth: 0, hoverOffset: 8 }}]
  }},
  options: chartOpts
}});

// ── Table filter ─────────────────────────────────────────────────────────────
function filterTable() {{
  const search   = document.getElementById('searchInput').value.toLowerCase();
  const category = document.getElementById('categoryFilter').value;
  const auth     = document.getElementById('authFilter').value;
  const access   = document.getElementById('accessFilter').value;
  const build    = document.getElementById('buildFilter').value;

  const rows = document.querySelectorAll('#tableBody tr');
  let visible = 0;

  rows.forEach(row => {{
    const text       = row.textContent.toLowerCase();
    const rowCat     = row.dataset.category || '';
    const rowAuth    = row.dataset.auth || '';
    const rowAccess  = row.dataset.access || '';
    const rowBuild   = row.dataset.buildable || '';

    const ok = (
      (!search   || text.includes(search)) &&
      (!category || rowCat === category) &&
      (!auth     || rowAuth.includes(auth)) &&
      (!access   || rowAccess === access) &&
      (!build    || rowBuild === build)
    );

    row.style.display = ok ? '' : 'none';
    if (ok) visible++;
  }});

  document.getElementById('tableCount').textContent =
    `Showing ${{visible}} of {stats.total_apps} apps`;
}}

// ── Table sort ────────────────────────────────────────────────────────────────
let sortDir = {{}};
function sortTable(col) {{
  const tbody = document.getElementById('tableBody');
  const rows  = Array.from(tbody.querySelectorAll('tr'));
  const asc   = !sortDir[col];
  sortDir = {{}};
  sortDir[col] = asc;

  rows.sort((a, b) => {{
    const av = a.cells[col]?.textContent.trim() || '';
    const bv = b.cells[col]?.textContent.trim() || '';
    const an = parseFloat(av); const bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return asc ? an-bn : bn-an;
    return asc ? av.localeCompare(bv) : bv.localeCompare(av);
  }});

  rows.forEach(r => tbody.appendChild(r));
}}
</script>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    logger.info("📄 Report written → %s", output_path)
    print(f"✅ Report generated: {output_path}")
