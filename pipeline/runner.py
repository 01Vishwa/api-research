"""
Pipeline Runner — orchestrates the full research → verify → insights flow.

Execution model:
  - Research phase: asyncio-based concurrent batches (BATCH_SIZE apps at a time)
  - Verification phase: sequential to avoid LLM rate-limit thrashing
  - Both phases are RESUMABLE — already-processed apps are skipped
  - No global mutable state; all coordination via files on disk
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn, TimeElapsedColumn

from agents.insight_generator import generate_insights, save_insights
from agents.researcher import research_app
from agents.verifier import verify_app
from config import (
    APPS_JSON_PATH,
    BATCH_SIZE,
    INSIGHTS_PATH,
    PASS2_PATH,
    RAW_PASS1_PATH,
    VERIFY_LOG_PATH,
)
from models.schema import AppRecord, VerificationLog

logger = logging.getLogger(__name__)
console = Console()


# ─── Persistence helpers ──────────────────────────────────────────────────────

def _load_apps() -> list[dict]:
    with open(APPS_JSON_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load_existing_records(path: Path) -> dict[int, dict]:
    """Load already-processed records keyed by app id."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {r["id"]: r for r in data}
    except Exception:
        return {}


def _save_records(records: list[dict], path: Path) -> None:
    path.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")


# ─── Research batch execution ─────────────────────────────────────────────────

async def _research_one(app_meta: dict, semaphore: asyncio.Semaphore) -> AppRecord:
    """Research a single app, respecting the concurrency semaphore."""
    async with semaphore:
        loop = asyncio.get_event_loop()
        record = await loop.run_in_executor(
            None,
            research_app,
            app_meta["id"],
            app_meta["app"],
            app_meta["category"],
            app_meta.get("hint", ""),
        )
        return record


async def _run_research_batch(
    apps: list[dict],
    existing: dict[int, dict],
    progress: Progress,
    task_id: TaskID,
) -> list[AppRecord]:
    """Run research for all apps, skipping already-done ones."""
    semaphore = asyncio.Semaphore(BATCH_SIZE)
    results: list[AppRecord] = []

    # Build tasks only for unprocessed apps
    todo = [a for a in apps if a["id"] not in existing]
    done = [AppRecord(**existing[a["id"]]) for a in apps if a["id"] in existing]

    console.print(
        f"[cyan]Research phase:[/] {len(done)} already done, "
        f"{len(todo)} to process."
    )

    if not todo:
        return done

    tasks = [_research_one(app, semaphore) for app in todo]

    for coro in asyncio.as_completed(tasks):
        try:
            record = await coro
            results.append(record)
            progress.advance(task_id)
            console.print(
                f"  [green]✓[/] [{record.id:>3}] {record.app:<30} "
                f"auth={record.auth_methods} conf={record.confidence:.2f}"
            )
        except Exception as exc:
            logger.error("Research task failed: %s", exc)
            progress.advance(task_id)

    return done + results


# ─── Verification phase ───────────────────────────────────────────────────────

def _run_verification(
    records: list[AppRecord],
    existing_verified: dict[int, dict],
    progress: Progress,
    task_id: TaskID,
) -> tuple[list[AppRecord], list[VerificationLog]]:
    """
    Verify all records. Skip already-verified ones.
    Returns (verified_records, verification_logs).
    """
    verified: list[AppRecord] = []
    logs: list[VerificationLog] = []

    for rec in records:
        # Already verified — skip re-processing
        if rec.id in existing_verified:
            verified_rec = AppRecord(**existing_verified[rec.id])
            verified.append(verified_rec)
            progress.advance(task_id)
            continue

        try:
            updated_rec, log = verify_app(rec)
            verified.append(updated_rec)
            logs.append(log)

            status_emoji = "✅" if str(log.status) == "confirmed" else "🔄"
            console.print(
                f"  {status_emoji} [{rec.id:>3}] {rec.app:<30} "
                f"status={log.status}"
            )
        except Exception as exc:
            logger.error("Verification failed for %s: %s", rec.app, exc)
            # Keep original record but flag it
            rec_copy = rec.model_copy()
            rec_copy.verifier_notes = f"Verification error: {exc}"
            verified.append(rec_copy)

        progress.advance(task_id)
        # Small sleep to reduce LLM rate-limit pressure
        time.sleep(0.5)

    return verified, logs


# ─── Main orchestrator ────────────────────────────────────────────────────────

async def run_full_pipeline(
    skip_verification: bool = False,
    skip_insights: bool = False,
) -> None:
    """
    Execute the full research → verify → insights pipeline.

    Args:
        skip_verification: If True, skip verification pass (faster, less accurate).
        skip_insights: If True, skip insight generation (for re-runs).
    """
    apps = _load_apps()
    total = len(apps)
    console.print(f"\n[bold cyan]AgentForge Pipeline[/] — {total} apps\n")

    # ── Phase 1: Research ──────────────────────────────────────────────────
    existing_pass1 = _load_existing_records(RAW_PASS1_PATH)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        research_task = progress.add_task(
            "[cyan]Phase 1: Research", total=total - len(existing_pass1)
        )

        t0 = time.time()
        pass1_records = await _run_research_batch(apps, existing_pass1, progress, research_task)
        research_time = time.time() - t0

    # Save pass-1 results
    _save_records([r.model_dump() for r in pass1_records], RAW_PASS1_PATH)
    console.print(
        f"\n[green]✅ Phase 1 complete[/] — {len(pass1_records)} records "
        f"in {research_time:.1f}s → {RAW_PASS1_PATH}\n"
    )

    # ── Phase 2: Verification ─────────────────────────────────────────────
    if skip_verification:
        console.print("[yellow]Skipping verification (--skip-verify flag set)[/]")
        verified_records = pass1_records
        all_logs: list[VerificationLog] = []
    else:
        existing_pass2 = _load_existing_records(PASS2_PATH)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            verify_task = progress.add_task(
                "[yellow]Phase 2: Verification", total=total
            )

            t1 = time.time()
            verified_records, all_logs = _run_verification(
                pass1_records, existing_pass2, progress, verify_task
            )
            verify_time = time.time() - t1

        # Save pass-2 results
        _save_records([r.model_dump() for r in verified_records], PASS2_PATH)

        # Save verification logs
        VERIFY_LOG_PATH.write_text(
            json.dumps([log_entry.model_dump() for log_entry in all_logs], indent=2, default=str),
            encoding="utf-8",
        )
        console.print(
            f"\n[green]✅ Phase 2 complete[/] — verified {len(verified_records)} records "
            f"in {verify_time:.1f}s → {PASS2_PATH}\n"
        )

    # ── Phase 3: Insights ─────────────────────────────────────────────────
    if not skip_insights:
        console.print("[magenta]Phase 3: Generating insights…[/]")
        stats = generate_insights(verified_records)
        save_insights(stats, INSIGHTS_PATH)

        console.print("\n[bold green]Pipeline complete![/]")
        console.print(f"  Auth dominant: {max(stats.auth_distribution, key=stats.auth_distribution.get, default='N/A')}")
        console.print(f"  Buildable today: {stats.buildable_count}/{stats.total_apps}")
        console.print(f"  Easy wins: {len(stats.easy_wins)}")
        console.print(f"  MCP coverage: {stats.mcp_exists_count}/{stats.total_apps}")
        console.print(f"  Avg confidence: {stats.avg_confidence:.2f}")


def run_pipeline(
    skip_verification: bool = False,
    skip_insights: bool = False,
) -> None:
    """Synchronous entry point for CLI."""
    asyncio.run(run_full_pipeline(skip_verification, skip_insights))
