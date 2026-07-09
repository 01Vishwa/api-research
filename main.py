"""
AgentForge CLI - entry point for the full research pipeline.

Commands:
  research   Run research pass on all 100 apps
  verify     Run verification pass on pass-1 results
  insights   Compute insights from verified results
  report     Generate the HTML report
  run        Run the complete pipeline end-to-end (default)
"""

from __future__ import annotations

import io
import json
import logging
import sys

# Force UTF-8 output on Windows to avoid charmap encode errors
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import click  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.logging import RichHandler  # noqa: E402

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True)],
)
# Also write to file
from config import PIPELINE_LOG_PATH  # noqa: E402
file_handler = logging.FileHandler(PIPELINE_LOG_PATH, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.getLogger().addHandler(file_handler)

logger = logging.getLogger("agentforge")
console = Console()


@click.group()
def cli():
    """AgentForge — Autonomous API Research & Verification Pipeline."""


@cli.command()
@click.option("--skip-verify", is_flag=True, default=False, help="Skip verification pass")
@click.option("--skip-insights", is_flag=True, default=False, help="Skip insight generation")
def run(skip_verify: bool, skip_insights: bool):
    """Run the complete research → verify → insights pipeline."""
    from pipeline.runner import run_pipeline
    console.print("[bold green]Starting AgentForge full pipeline…[/]")
    run_pipeline(skip_verification=skip_verify, skip_insights=skip_insights)


@cli.command()
def research():
    """Research pass only — outputs raw_pass1.json."""
    from pipeline.runner import run_pipeline
    run_pipeline(skip_verification=True, skip_insights=True)


@cli.command()
def verify():
    """Verification pass on existing pass-1 results — outputs pass2_verified.json."""
    from config import RAW_PASS1_PATH, PASS2_PATH, VERIFY_LOG_PATH
    from models.schema import AppRecord, VerificationLog
    from agents.verifier import verify_app

    if not RAW_PASS1_PATH.exists():
        console.print("[red]Error:[/] raw_pass1.json not found. Run 'research' first.")
        sys.exit(1)

    records_data = json.loads(RAW_PASS1_PATH.read_text(encoding="utf-8"))
    records = [AppRecord(**r) for r in records_data]

    verified: list[AppRecord] = []
    logs: list[VerificationLog] = []

    import time
    for rec in records:
        console.print(f"  Verifying [cyan]{rec.app}[/]…")
        try:
            updated, log = verify_app(rec)
            verified.append(updated)
            logs.append(log)
        except Exception as exc:
            console.print(f"  [red]Error verifying {rec.app}:[/] {exc}")
            verified.append(rec)
        time.sleep(0.5)

    PASS2_PATH.write_text(
        json.dumps([r.model_dump() for r in verified], indent=2, default=str),
        encoding="utf-8",
    )
    VERIFY_LOG_PATH.write_text(
        json.dumps([log_entry.model_dump() for log_entry in logs], indent=2, default=str),
        encoding="utf-8",
    )
    console.print(f"[green]✅ Verification complete → {PASS2_PATH}[/]")


@cli.command()
def insights():
    """Generate insights from verified results — outputs insights.json."""
    from config import PASS2_PATH, RAW_PASS1_PATH, INSIGHTS_PATH
    from models.schema import AppRecord
    from agents.insight_generator import generate_insights, save_insights

    source = PASS2_PATH if PASS2_PATH.exists() else RAW_PASS1_PATH
    if not source.exists():
        console.print("[red]Error:[/] No research results found. Run 'run' or 'research' first.")
        sys.exit(1)

    records_data = json.loads(source.read_text(encoding="utf-8"))
    records = [AppRecord(**r) for r in records_data]
    stats = generate_insights(records)
    save_insights(stats, INSIGHTS_PATH)
    console.print(f"[green]✅ Insights generated → {INSIGHTS_PATH}[/]")


@cli.command()
def report():
    """Generate the HTML report from existing results."""
    from config import PASS2_PATH, RAW_PASS1_PATH, INSIGHTS_PATH, VERIFY_LOG_PATH, REPORT_HTML_PATH
    from models.schema import AppRecord, InsightStats, VerificationLog
    from agents.insight_generator import generate_insights
    from report.generator import generate_report

    source = PASS2_PATH if PASS2_PATH.exists() else RAW_PASS1_PATH
    if not source.exists():
        console.print("[red]Error:[/] No research results found. Run 'run' first.")
        sys.exit(1)

    records_data = json.loads(source.read_text(encoding="utf-8"))
    records = [AppRecord(**r) for r in records_data]

    # Insights (recompute if needed)
    if INSIGHTS_PATH.exists():
        stats = InsightStats(**json.loads(INSIGHTS_PATH.read_text(encoding="utf-8")))
    else:
        stats = generate_insights(records)

    # Verification logs
    logs: list[VerificationLog] = []
    if VERIFY_LOG_PATH.exists():
        logs_data = json.loads(VERIFY_LOG_PATH.read_text(encoding="utf-8"))
        logs = [VerificationLog(**log_entry) for log_entry in logs_data]

    generate_report(records, stats, logs, REPORT_HTML_PATH)
    console.print(f"[green]✅ Report generated → {REPORT_HTML_PATH}[/]")


@cli.command()
def export():
    """Export results as CSV."""
    import csv
    from config import PASS2_PATH, RAW_PASS1_PATH, OUTPUT_DIR
    from models.schema import AppRecord

    source = PASS2_PATH if PASS2_PATH.exists() else RAW_PASS1_PATH
    if not source.exists():
        console.print("[red]No results to export.[/]")
        sys.exit(1)

    records_data = json.loads(source.read_text(encoding="utf-8"))
    records = [AppRecord(**r) for r in records_data]

    csv_path = OUTPUT_DIR / "apps.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "app", "category", "one_line", "auth_methods",
            "access_model", "api_types", "api_breadth", "webhooks",
            "existing_mcp", "buildable_today", "blocker",
            "confidence", "verification_status", "evidence_url",
        ])
        for r in records:
            writer.writerow([
                r.id, r.app, r.category, r.one_line,
                "|".join(str(m) for m in r.auth_methods),
                r.access_model,
                "|".join(str(t) for t in r.api_surface.types),
                r.api_surface.breadth,
                r.api_surface.webhooks,
                r.existing_mcp.exists,
                r.buildable_today,
                r.blocker,
                r.confidence,
                r.verification_status,
                r.evidence_url,
            ])

    console.print(f"[green]✅ CSV exported → {csv_path}[/]")


if __name__ == "__main__":
    cli()
