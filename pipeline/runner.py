"""
Pipeline Runner — orchestrates the full research → verify → insights flow.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import sys
import time
from pathlib import Path

from rich.console import Console

from agents.insight_generator import generate_insights, save_insights
from agents.researcher import research_app
from agents.verifier import verify_app
from config import (
    APPS_JSON_PATH,
    INSIGHTS_PATH,
    OUTPUT_DIR,
    PASS2_PATH,
    RAW_PASS1_PATH,
    VERIFY_LOG_PATH,
)
from models.schema import AppRecord, VerificationLog, VerificationStatus

logger = logging.getLogger(__name__)
console = Console()

CATEGORY_ORDER = [
    "CRM and Sales",
    "Support and Helpdesk",
    "Communications and Messaging",
    "Marketing, Ads, Email and Social",
    "Ecommerce",
    "Data, SEO and Scraping",
    "Developer, Infra and Data platforms",
    "Productivity and Project Management",
    "Finance and Fintech",
    "AI, Research and Media-native"
]

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


def _save_records(records_dict: dict[int, dict], path: Path) -> None:
    path.write_text(json.dumps(list(records_dict.values()), indent=2, default=str), encoding="utf-8")


def _append_to_csv(record: AppRecord, csv_path: Path) -> None:
    file_exists = csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "id", "app", "category", "one_line", "auth_methods",
                "access_model", "api_types", "api_breadth", "webhooks",
                "existing_mcp", "buildable_today", "blocker",
                "confidence", "verification_status", "evidence_url",
                "verifier_notes", "fetch_tool", "corrections_made",
                "tool_source", "failure_reason"
            ])
        writer.writerow([
            record.id, record.app, record.category, record.one_line,
            "|".join(str(m) for m in record.auth_methods),
            record.access_model,
            "|".join(str(t) for t in record.api_surface.types),
            record.api_surface.breadth,
            record.api_surface.webhooks,
            record.existing_mcp.exists,
            record.buildable_today,
            record.blocker,
            f"{record.confidence:.2f}",
            record.verification_status,
            record.evidence_url,
            record.verifier_notes.replace("\n", " ")[:200],
            record.fetch_tool,
            "yes" if record.verification_status == VerificationStatus.CORRECTED else "no",
            record.tool_source,
            record.failure_reason or ""
        ])


# ─── Main orchestrator ────────────────────────────────────────────────────────

async def run_full_pipeline(
    skip_research: bool = False,
    skip_verification: bool = False,
    skip_insights: bool = False,
    force: bool = False,
    auto: bool = False,
) -> None:
    apps = _load_apps()
    total = len(apps)
    console.print(f"\n[bold cyan]AgentForge Pipeline[/] — {total} apps\n")

    from config import VERIFIER_LLM_PROVIDER
    if VERIFIER_LLM_PROVIDER == "openai":
        est_calls = total * 2
        console.print(f"  [yellow]Budget Check:[/] Estimating ~{est_calls} LLM calls (research + verify). At standard OpenAI gpt-4o-mini limits (500 RPM), this should complete in < {max(1, est_calls // 400)} minutes without throttling.")

    existing_pass1 = _load_existing_records(RAW_PASS1_PATH)
    existing_pass2 = _load_existing_records(PASS2_PATH)
    existing_logs = _load_existing_records(VERIFY_LOG_PATH) # keyed by id if we assume 1 log per app, but logs don't have id natively, wait

    # For logs, let's just load them as a list and rewrite
    logs_list = []
    if VERIFY_LOG_PATH.exists():
        try:
            logs_list = json.loads(VERIFY_LOG_PATH.read_text(encoding="utf-8"))
        except:
            pass

    # Checkpoint messaging
    if not force and not skip_research and len(existing_pass1) >= total:
        console.print("[yellow]Checkpoint detected: 100/100 apps already researched. Skipping. Run with --force to rebuild.[/]")
        skip_research = True

    csv_path = OUTPUT_DIR / "verification.csv"

    # Group apps by category
    apps_by_cat = {c: [] for c in CATEGORY_ORDER}
    for app in apps:
        cat = app["category"]
        if cat in apps_by_cat:
            apps_by_cat[cat].append(app)
        else:
            # Fallback for unexpected categories
            if "Other" not in apps_by_cat:
                apps_by_cat["Other"] = []
                CATEGORY_ORDER.append("Other")
            apps_by_cat["Other"].append(app)

    # Tracking for summary
    total_verified = 0
    total_corrected = 0
    total_failed = 0
    sum_confidence = 0.0

    for cat_idx, category in enumerate(CATEGORY_ORDER):
        cat_apps = apps_by_cat[category]
        if not cat_apps:
            continue

        console.print(f"\n[bold blue]=== Category {cat_idx+1}/{len(CATEGORY_ORDER)}: {category} ({len(cat_apps)} apps) ===[/]")
        
        cat_verified = 0
        cat_corrected = 0
        cat_failed = 0
        cat_sum_conf = 0.0

        skip_category = False

        for app_meta in cat_apps:
            if skip_category:
                break
                
            app_id = app_meta["id"]
            app_name = app_meta["app"]
            
            # --- Research Phase ---
            rec1_dict = existing_pass1.get(app_id)
            if not skip_research and (force or not rec1_dict):
                console.print(f"\n  [cyan]Researching:[/] {app_name}...")
                # We need to run it in a thread/event loop
                loop = asyncio.get_event_loop()
                rec1 = await loop.run_in_executor(
                    None,
                    research_app,
                    app_id,
                    app_name,
                    category,
                    app_meta.get("hint", ""),
                )
                rec1_dict = rec1.model_dump()
                existing_pass1[app_id] = rec1_dict
                _save_records(existing_pass1, RAW_PASS1_PATH)
            
            if not rec1_dict:
                # Should only happen if skip_research=True and no pass1 data exists
                console.print(f"  [red]Skipping {app_name}: No research data available.[/]")
                continue
                
            rec1 = AppRecord(**rec1_dict)

            # --- Verification Phase ---
            rec2_dict = existing_pass2.get(app_id)
            if not skip_verification and (force or not rec2_dict):
                console.print(f"  [yellow]Verifying:[/] {app_name}...")
                try:
                    rec2, log = verify_app(rec1)
                except Exception as exc:
                    logger.error("Verification critically failed for %s: %s", app_name, exc)
                    rec2 = rec1.model_copy()
                    rec2.verification_status = VerificationStatus.FAILED
                    rec2.verifier_notes = f"Critical error: {exc}"
                    log = VerificationLog(app=app_name, status=VerificationStatus.FAILED, verifier_notes=str(exc))
                
                rec2_dict = rec2.model_dump()
                existing_pass2[app_id] = rec2_dict
                _save_records(existing_pass2, PASS2_PATH)
                
                # Update logs list
                # Remove old log for this app if exists, then append
                logs_list = [l for l in logs_list if l.get("app") != app_name]
                logs_list.append(log.model_dump())
                VERIFY_LOG_PATH.write_text(json.dumps(logs_list, indent=2, default=str), encoding="utf-8")

                _append_to_csv(rec2, csv_path)
            
            if not rec2_dict:
                rec2_dict = rec1_dict
            rec2 = AppRecord(**rec2_dict)

            # Tracking
            total_verified += 1
            cat_verified += 1
            sum_confidence += rec2.confidence
            cat_sum_conf += rec2.confidence
            if rec2.verification_status == VerificationStatus.CORRECTED:
                total_corrected += 1
                cat_corrected += 1
            elif rec2.verification_status == VerificationStatus.FAILED:
                total_failed += 1
                cat_failed += 1

            # --- Confirmation Gate ---
            if not skip_verification:
                reason_str = f", reason: {rec2.failure_reason}" if rec2.failure_reason else ""
                console.print(f"  [green]✓[/] [{category}] {app_name} — done (confidence: {rec2.confidence:.2f}, status: {rec2.verification_status}{reason_str})")
                if not auto:
                    # Flush stdout to ensure prompt is visible
                    sys.stdout.flush()
                    while True:
                        ans = input(f"Continue to next app? [Enter = yes / s = skip category / q = quit]: ").strip().lower()
                        if ans in ("", "y", "yes"):
                            break
                        elif ans == "s":
                            skip_category = True
                            break
                        elif ans == "q":
                            console.print("[yellow]Quitting safely. Progress has been saved.[/]")
                            return
                        else:
                            print("Invalid input.")

        # End of category summary
        if cat_verified > 0:
            avg_conf = cat_sum_conf / cat_verified
            console.print(f"\n[magenta]--- Category Summary: {category} ---[/]")
            console.print(f"Apps Processed: {cat_verified} | Corrected: {cat_corrected} | Failed: {cat_failed} | Avg Conf: {avg_conf:.2f}")

    # Final summary
    if not skip_verification and total_verified > 0:
        avg_conf = sum_confidence / total_verified
        console.print(f"\n[bold green]=== Final Verification Summary ===[/]")
        console.print(f"Total Apps Processed: {total_verified}")
        console.print(f"Total Corrected:      {total_corrected}")
        console.print(f"Total Failed:         {total_failed}")
        console.print(f"Average Confidence:   {avg_conf:.2f}")
        
        # We don't have the manual spot check accuracy here, so we just print a placeholder or omit
        # Since it asks for pass1->pass2 accuracy delta, that's just the inverse of the correction rate
        accuracy = ((total_verified - total_corrected) / total_verified) * 100
        console.print(f"Pass1 → Pass2 match:  {accuracy:.1f}%")

    # ── Phase 3: Insights ─────────────────────────────────────────────────
    if not skip_insights and not auto:
        ans = input(f"\nGenerate insights? [Enter = yes / n = no]: ").strip().lower()
        if ans in ("n", "no"):
            skip_insights = True

    if not skip_insights:
        console.print("\n[magenta]Phase 3: Generating insights…[/]")
        records = [AppRecord(**r) for r in existing_pass2.values()]
        if not records:
            records = [AppRecord(**r) for r in existing_pass1.values()]
            
        stats = generate_insights(records)
        save_insights(stats, INSIGHTS_PATH)

        console.print("\n[bold green]Pipeline complete![/]")
        console.print(f"  Auth dominant: {max(stats.auth_distribution, key=stats.auth_distribution.get, default='N/A')}")
        console.print(f"  Buildable today: {stats.buildable_count}/{stats.total_apps}")
        console.print(f"  Easy wins: {len(stats.easy_wins)}")
        console.print(f"  MCP coverage: {stats.mcp_exists_count}/{stats.total_apps}")
        console.print(f"  Avg confidence: {stats.avg_confidence:.2f}")


def run_pipeline(
    skip_research: bool = False,
    skip_verification: bool = False,
    skip_insights: bool = False,
    force: bool = False,
    auto: bool = False,
) -> None:
    """Synchronous entry point for CLI."""
    asyncio.run(run_full_pipeline(skip_research, skip_verification, skip_insights, force, auto))
