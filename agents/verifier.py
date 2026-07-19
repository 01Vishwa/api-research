"""
Verification Agent — independently re-derives answers from evidence URLs.

Graph topology (strictly acyclic):
  START → load_record → fetch_evidence → re_derive → diff_compare → END

The verifier NEVER sees the researcher's conclusions at inference time —
it only gets the evidence URL and independently answers the same questions.
This ensures genuine independence, not rubber-stamping.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from config import (
    LANGGRAPH_RECURSION,
    LLM_MAX_TOKENS,
)
from schemas.schema import (
    AppRecord,
    VerificationLog,
    VerificationRecord,
    VerificationStatus,
)
from tools.fetcher import fetch_page_sync
from tools.search import web_search_sync

logger = logging.getLogger(__name__)


# ─── LLM setup ───────────────────────────────────────────────────────────────

def _get_llm():
    from config import (
        GITHUB_TOKEN, GITHUB_MODEL_BASE_URL, OPENAI_API_KEY, 
        LLM_MAX_TOKENS, LLM_MODEL,
        VERIFIER_LLM_PROVIDER, VERIFIER_LLM_MODEL, VERIFIER_LLM_TEMPERATURE
    )
    from langchain_openai import ChatOpenAI

    if VERIFIER_LLM_PROVIDER == "openai":
        if not OPENAI_API_KEY:
            raise EnvironmentError("OPENAI_API_KEY is not set for verifier LLM.")
        return ChatOpenAI(
            model=VERIFIER_LLM_MODEL,
            api_key=OPENAI_API_KEY,
            temperature=VERIFIER_LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
            max_retries=0,
        )
    else:
        api_key = GITHUB_TOKEN or OPENAI_API_KEY
        if not api_key:
            raise EnvironmentError("GITHUB_TOKEN (or OPENAI_API_KEY) is not set.")

        return ChatOpenAI(
            model=VERIFIER_LLM_MODEL,
            api_key=api_key,
            base_url=GITHUB_MODEL_BASE_URL if GITHUB_TOKEN else None,
            max_tokens=LLM_MAX_TOKENS,
            max_retries=0,
            temperature=VERIFIER_LLM_TEMPERATURE,
        )


# ─── Verifier prompt ─────────────────────────────────────────────────────────

VERIFIER_SYSTEM_PROMPT = """You are an independent API integration auditor.
You have been given documentation text. Extract the following facts directly from the text.
Do NOT guess or use general knowledge — only use what is explicitly stated in the documentation.

Return ONLY a JSON object:
{
  "auth_methods": ["OAuth2" | "API Key" | "Basic Auth" | "Bearer Token" | "HMAC" | "JWT" | "No Auth" | "Other" | "Unknown"],
  "access_model": "self-serve" | "paid-plan-gated" | "admin-approval" | "partner-gated" | "contact-sales" | "unknown",
  "api_types": ["REST" | "GraphQL" | "SOAP" | "gRPC" | "WebSocket" | "None" | "Unknown"],
  "buildable_today": true | false | null,
  "blocker": "none" | "partner-approval-required" | "no-public-api" | "contact-sales-required" | "complex-oauth-scopes" | "rate-limit-unclear" | "no-public-docs" | "enterprise-only" | "deprecated-api" | "paid-account-required" | "unknown",
  "confidence": <0.0 to 1.0>,
  "source_quote": "<exact quote from docs proving auth method, or 'not explicitly stated'>"
}

If something is not stated in the text, use "Unknown" or null — do NOT invent answers.
"""


# ─── Graph State ─────────────────────────────────────────────────────────────

class VerifierState(TypedDict):
    app_name: str
    original_record: dict       # From research pass-1
    evidence_url: str
    page_text: str
    fetch_tool: str
    tool_source: str
    failure_reason: str
    re_derived: dict            # Verifier's independent extraction
    verification_log: dict      # VerificationLog dict
    error: str


# ─── Nodes ───────────────────────────────────────────────────────────────────

def load_record_node(state: VerifierState) -> VerifierState:
    """Extract evidence URL from the record."""
    record = state["original_record"]
    evidence_url = record.get("evidence_url", "")
    return {**state, "evidence_url": evidence_url}


def fetch_evidence_node(state: VerifierState) -> VerifierState:
    """
    Fetch the evidence URL independently.
    If that fails, do a fresh search to find a reliable source.
    """
    url = state["evidence_url"]
    app_name = state["app_name"]
    page_text = ""
    fetch_tool = "Unknown"
    tool_source = "Unknown"
    failure_reason = ""

    if url:
        page_text, fetch_tool, failure_reason = fetch_page_sync(url)
        page_text = page_text or ""
        tool_source = fetch_tool
        if failure_reason is None:
            failure_reason = ""

    if not page_text or len(page_text) < 200:
        # Evidence URL was stale/unavailable — do a fresh search
        logger.info("  Verifier: evidence URL failed, doing fresh search for %s", app_name)
        results = web_search_sync(f"{app_name} developer API documentation authentication", max_results=3)
        if isinstance(results, tuple):
            results, t_source, s_reason = results
            tool_source = t_source
            if not failure_reason and s_reason:
                failure_reason = s_reason
                
        if results:
            # Try fetching the first good result
            for r in results:
                text, tool, reason = fetch_page_sync(r.get("url", ""))
                text = text or ""
                if len(text) > 300:
                    page_text = text
                    fetch_tool = tool
                    tool_source = tool
                    failure_reason = reason or ""
                    state = {**state, "evidence_url": r["url"]}
                    break
                elif reason:
                    failure_reason = reason
            if not page_text:
                snippets = " ".join(r.get("snippet", "") for r in results)
                page_text = snippets or "No documentation found."
                fetch_tool = "Search Snippets"
                tool_source = "Search Snippets"
                if not failure_reason:
                    failure_reason = "no_docs_found"

    return {**state, "page_text": page_text, "fetch_tool": fetch_tool, "tool_source": tool_source, "failure_reason": failure_reason}


def re_derive_node(state: VerifierState) -> VerifierState:
    """Run LLM independently over the evidence to derive auth/access facts."""
    llm = _get_llm()
    app_name = state["app_name"]
    context = state["page_text"][:6000]

    user_msg = f"""App: {app_name}
Evidence URL: {state['evidence_url']}

--- Documentation ---
{context}

Now extract the integration facts for {app_name} from the above documentation only."""

    from tenacity import retry, stop_after_attempt, wait_exponential

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=2, max=60))
    def _call_llm():
        import time
        time.sleep(2.5)
        return llm.invoke([
            SystemMessage(content=VERIFIER_SYSTEM_PROMPT),
            HumanMessage(content=user_msg),
        ])

    try:
        response = _call_llm()
        raw = response.content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        re_derived = json.loads(raw)
        return {**state, "re_derived": re_derived}
    except Exception as exc:
        logger.error("Verifier LLM failed for %s: %s", app_name, exc)
        reason = "llm_verification_429_exhausted" if "429" in str(exc) else "llm_error"
        return {**state, "re_derived": {}, "error": str(exc), "failure_reason": reason}


def diff_compare_node(state: VerifierState) -> VerifierState:
    """
    Compare verifier's derivation against original research output.
    Produce a VerificationLog with all corrections.
    """
    app_name = state["app_name"]
    original = state["original_record"]
    derived = state.get("re_derived", {})

    corrections: list[VerificationRecord] = []
    changed_any = False

    # Helper: normalise list to sorted set for comparison
    def _norm_list(v: Any) -> set:
        if isinstance(v, list):
            return {str(x).lower() for x in v}
        return {str(v).lower()}

    def _check(field: str, orig_val: Any, new_val: Any):
        nonlocal changed_any
        orig_set = _norm_list(orig_val)
        new_set  = _norm_list(new_val)

        changed = bool(new_val) and (orig_set != new_set) and "unknown" not in new_set
        if changed:
            changed_any = True

        corrections.append(VerificationRecord(
            app=app_name,
            field=field,
            original_value=str(orig_val),
            verified_value=str(new_val) if new_val else str(orig_val),
            changed=changed,
            verifier_confidence=float(derived.get("confidence", 0.0)),
            source_url=state["evidence_url"],
            notes=derived.get("source_quote", ""),
        ))

    # Compare key fields
    _check("auth_methods",  original.get("auth_methods"), derived.get("auth_methods"))
    _check("access_model",  original.get("access_model"), derived.get("access_model"))
    _check("api_types",     original.get("api_surface", {}).get("types"), derived.get("api_types"))
    _check("buildable_today", original.get("buildable_today"), derived.get("buildable_today"))
    _check("blocker",       original.get("blocker"), derived.get("blocker"))

    # Determine status
    if state.get("error"):
        status = VerificationStatus.FAILED
    elif not derived:
        status = VerificationStatus.NEEDS_HUMAN
    elif changed_any:
        status = VerificationStatus.CORRECTED
    else:
        status = VerificationStatus.CONFIRMED

    log = VerificationLog(
        app=app_name,
        status=status,
        corrections=[c for c in corrections if c.changed],   # Only log actual corrections
        verifier_notes=derived.get("source_quote", "") if not state.get("error") else state.get("error"),
        fetch_tool=state.get("fetch_tool", "Unknown"),
        tool_source=state.get("tool_source", "Unknown"),
        failure_reason=state.get("failure_reason") if status == VerificationStatus.FAILED else None,
    )

    return {**state, "verification_log": log.model_dump()}


# ─── Graph assembly ───────────────────────────────────────────────────────────

def build_verifier_graph() -> Any:
    """
    Build the verification StateGraph.
    Topology (DAG — no cycles):
      START → load_record → fetch_evidence → re_derive → diff_compare → END
    """
    graph = StateGraph(VerifierState)

    graph.add_node("load_record",   load_record_node)
    graph.add_node("fetch_evidence", fetch_evidence_node)
    graph.add_node("re_derive",     re_derive_node)
    graph.add_node("diff_compare",  diff_compare_node)

    graph.add_edge(START,             "load_record")
    graph.add_edge("load_record",     "fetch_evidence")
    graph.add_edge("fetch_evidence",  "re_derive")
    graph.add_edge("re_derive",       "diff_compare")
    graph.add_edge("diff_compare",    END)

    return graph.compile()


_verifier_graph = None


def verify_app(original_record: AppRecord) -> tuple[AppRecord, VerificationLog]:
    """
    Verify a single AppRecord.

    Returns:
        (updated_record, verification_log)
        updated_record has corrections applied where the verifier found mismatches.
    """
    global _verifier_graph
    if _verifier_graph is None:
        _verifier_graph = build_verifier_graph()

    record_dict = original_record.model_dump()

    initial: VerifierState = {
        "app_name": original_record.app,
        "original_record": record_dict,
        "evidence_url": original_record.evidence_url,
        "page_text": "",
        "fetch_tool": "Unknown",
        "tool_source": "Unknown",
        "failure_reason": "",
        "re_derived": {},
        "verification_log": {},
        "error": "",
    }

    final = _verifier_graph.invoke(
        initial,
        config={"recursion_limit": LANGGRAPH_RECURSION},
    )

    log_dict = final.get("verification_log", {})
    log = VerificationLog(**log_dict) if log_dict else VerificationLog(
        app=original_record.app,
        status=VerificationStatus.NEEDS_HUMAN,
    )

    # Apply corrections back to the record
    derived = final.get("re_derived", {})
    updated = original_record.model_copy()

    if derived and log.status in (
        VerificationStatus.CONFIRMED, VerificationStatus.CORRECTED
    ):
        from pipeline.normalizer import normalize_record
        updated = normalize_record(updated, derived)

    updated.verification_status = log.status
    updated.verifier_notes = log.verifier_notes
    updated.fetch_tool = log.fetch_tool
    updated.tool_source = log.tool_source
    if log.failure_reason:
        updated.failure_reason = log.failure_reason

    if log.status == VerificationStatus.FAILED:
        updated.confidence = 0.0
    elif updated.fetch_tool in ("Search Snippets", "Failed", "Unknown"):
        updated.confidence = min(updated.confidence, 0.3)

    return updated, log
