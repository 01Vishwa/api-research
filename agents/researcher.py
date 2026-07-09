"""
Research Agent — LangGraph-based agent that researches a single app.

Graph topology (strictly acyclic — no loops or deadlocks):

  START → plan_search → execute_search → fetch_docs → extract_info → END

Each node is a pure function; state flows forward only. The recursion_limit
config ensures the graph never spins forever even if a node misbehaves.
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
    LLM_TEMPERATURE,
)
from models.schema import (
    AccessModel,
    APIType,
    AppRecord,
    APISurface,
    AuthMethod,
    Blocker,
    Breadth,
    MCPInfo,
    VerificationStatus,
)
from tools.fetcher import fetch_page_sync
from tools.search import web_search_sync

logger = logging.getLogger(__name__)


# ─── LLM setup ───────────────────────────────────────────────────────────────

def _get_llm():
    """Return a ChatOpenAI instance pointing to GitHub Models (or OpenAI)."""
    from config import GITHUB_TOKEN, GITHUB_MODEL_BASE_URL, LLM_MODEL, OPENAI_API_KEY
    from langchain_openai import ChatOpenAI

    api_key = GITHUB_TOKEN or OPENAI_API_KEY
    if not api_key:
        raise EnvironmentError("GITHUB_TOKEN (or OPENAI_API_KEY) is not set.")

    return ChatOpenAI(
        model=LLM_MODEL,
        api_key=api_key,
        base_url=GITHUB_MODEL_BASE_URL if GITHUB_TOKEN else None,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        max_retries=0,
    )

# ─── Graph State ─────────────────────────────────────────────────────────────

class ResearchState(TypedDict):
    # Input
    app_id: int
    app_name: str
    category: str
    hint_url: str

    # Intermediate
    search_queries: list[str]
    search_results: list[dict]
    page_text: str
    evidence_url: str
    fetch_tool: str
    tool_source: str
    failure_reason: str

    # Output
    extraction: dict       # Raw LLM extraction
    final_record: dict     # Validated AppRecord dict
    error: str


# ─── Extraction prompt ────────────────────────────────────────────────────────

EXTRACTION_SYSTEM_PROMPT = """You are an expert API researcher for Composio, an AI agent infrastructure company.
Your job: extract structured integration metadata from developer documentation.

You MUST return a valid JSON object with EXACTLY these fields:
{
  "one_line": "<one sentence describing what the app does>",
  "auth_methods": ["OAuth2" | "API Key" | "Basic Auth" | "Bearer Token" | "HMAC" | "JWT" | "No Auth" | "Other" | "Unknown"],
  "access_model": "self-serve" | "paid-plan-gated" | "admin-approval" | "partner-gated" | "contact-sales" | "unknown",
  "api_types": ["REST" | "GraphQL" | "SOAP" | "gRPC" | "WebSocket" | "None" | "Unknown"],
  "api_breadth": "broad" | "moderate" | "narrow" | "none" | "unknown",
  "webhooks": true | false,
  "rate_limits_documented": true | false,
  "api_notes": "<brief notes on API surface>",
  "existing_mcp": true | false,
  "mcp_link": null | "<url>",
  "mcp_official": true | false,
  "developer_portal_url": "<url or null>",
  "buildable_today": true | false,
  "blocker": "none" | "partner-approval-required" | "no-public-api" | "contact-sales-required" | "complex-oauth-scopes" | "rate-limit-unclear" | "no-public-docs" | "enterprise-only" | "deprecated-api" | "paid-account-required" | "unknown",
  "evidence_url": "<most authoritative docs URL found>",
  "secondary_urls": ["<other relevant urls>"],
  "confidence": <0.0 to 1.0>
}

Rules:
- auth_methods is a LIST — include ALL that apply.
- "self-serve" = developer can get credentials free or on trial without contacting sales.
- "buildable_today" = true if there is a documented public API + self-serve or paid-plan-gated access.
- confidence = how sure you are based on evidence quality (0=no info found, 1=authoritative docs read).
- Return ONLY the JSON object. No explanation, no markdown fences.
"""


# ─── Node implementations ─────────────────────────────────────────────────────

def plan_search_node(state: ResearchState) -> ResearchState:
    app = state["app_name"]
    hint = state["hint_url"]

    queries = [
        f"{app} developer API documentation authentication",
        f"{app} REST API OAuth2 API key developer portal",
        f"{app} API pricing free tier developer access",
        f"site:{hint} authentication API" if hint else f"{app} MCP server existing",
    ]
    # Remove duplicates while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique.append(q)

    return {**state, "search_queries": unique, "error": ""}


def execute_search_node(state: ResearchState) -> ResearchState:
    """Run the search queries and collect results."""
    all_results: list[dict] = []
    tool_source = "Unknown"
    failure_reason = ""

    for query in state["search_queries"][:3]:   # max 3 queries per app
        results, t_source, reason = web_search_sync(query, max_results=4)
        all_results.extend(results)
        if t_source != "Unknown":
            tool_source = t_source
        if reason:
            failure_reason = reason

    # Deduplicate by URL
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for r in all_results:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped.append(r)

    return {**state, "search_results": deduped[:12], "tool_source": tool_source, "failure_reason": failure_reason or ""}


def fetch_docs_node(state: ResearchState) -> ResearchState:
    """
    Fetch the most promising documentation page.
    Priority: hint_url → first search result URL → skip.
    """
    hint = state.get("hint_url", "")
    results = state.get("search_results", [])

    # Build candidate list: hint first, then search results
    candidates: list[str] = []
    if hint and not hint.startswith("http"):
        hint = "https://" + hint
    if hint:
        candidates.append(hint)

    for r in results:
        url = r.get("url", "")
        if url and url not in candidates:
            candidates.append(url)

    page_text = ""
    evidence_url = ""
    fetch_tool = "Unknown"
    tool_source = state.get("tool_source", "Unknown")
    failure_reason = state.get("failure_reason", "")

    for url in candidates[:4]:     # try up to 4 URLs
        text, tool_used, reason = fetch_page_sync(url)
        if text and len(text) > 300:
            page_text = text
            evidence_url = url
            fetch_tool = tool_used
            tool_source = tool_used
            failure_reason = reason or ""
            logger.debug("✓ Fetched %d chars from %s via %s", len(text), url, tool_used)
            break
        elif reason:
            failure_reason = reason

    # If we couldn't fetch, use search snippets as context
    if not page_text:
        snippets = "\n\n".join(
            f"[{r.get('title','')}] {r.get('url','')}\n{r.get('snippet','')}"
            for r in results[:6]
        )
        page_text = snippets or "No documentation found."
        evidence_url = results[0]["url"] if results else ""
        fetch_tool = "Search Snippets"
        tool_source = "Search Snippets"
        if not failure_reason:
            failure_reason = "no_docs_found"

    return {**state, "page_text": page_text, "evidence_url": evidence_url, "fetch_tool": fetch_tool, "tool_source": tool_source, "failure_reason": failure_reason}


def extract_info_node(state: ResearchState) -> ResearchState:
    """Use LLM to extract structured metadata from the fetched docs."""
    llm = _get_llm()
    app = state["app_name"]
    category = state["category"]
    context = state["page_text"][:8000]   # stay well within token budget

    # Supplement with search snippets for breadth
    snippets = "\n".join(
        f"- {r.get('title','')} ({r.get('url','')}): {r.get('snippet','')[:200]}"
        for r in state.get("search_results", [])[:5]
    )

    user_msg = f"""App: {app}
Category: {category}
Hint URL: {state.get('hint_url', 'N/A')}

--- Documentation Content ---
{context}

--- Additional Search Results ---
{snippets}

Extract the integration metadata JSON for {app}."""

    from tenacity import retry, stop_after_attempt, wait_exponential

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=2, max=60))
    def _call_llm():
        import time
        time.sleep(2.5)
        return llm.invoke([
            SystemMessage(content=EXTRACTION_SYSTEM_PROMPT),
            HumanMessage(content=user_msg),
        ])

    try:
        response = _call_llm()
        raw_text = response.content.strip()

        # Strip markdown fences if present
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

        extraction = json.loads(raw_text)
        logger.info("✅ Extracted data for %s (confidence=%.2f)", app, extraction.get("confidence", 0))
        return {**state, "extraction": extraction}

    except json.JSONDecodeError as exc:
        logger.error("JSON parse error for %s: %s", app, exc)
        return {**state, "extraction": {}, "error": f"JSON parse error: {exc}", "failure_reason": "json_parse_error"}
    except Exception as exc:
        logger.error("LLM error for %s: %s", app, exc)
        reason = "llm_verification_429_exhausted" if "429" in str(exc) else "llm_error"
        return {**state, "extraction": {}, "error": str(exc), "failure_reason": reason}


def build_record_node(state: ResearchState) -> ResearchState:
    """Convert raw extraction dict → validated AppRecord."""
    ext = state.get("extraction", {})
    app_id = state["app_id"]
    app_name = state["app_name"]
    category = state["category"]

    if not ext:
        # Return a minimal record flagging failure
        record = AppRecord(
            id=app_id,
            app=app_name,
            category=category,
            one_line="Research failed — see error log",
            confidence=0.0,
            verification_status=VerificationStatus.NEEDS_HUMAN,
            verifier_notes=state.get("error", "Unknown error"),
            tool_source=state.get("tool_source", "Unknown"),
            failure_reason=state.get("failure_reason"),
        )
        return {**state, "final_record": record.model_dump()}

    def _parse_enum_list(values: list[str], enum_cls, default) -> list:
        result = []
        for v in values:
            try:
                result.append(enum_cls(v))
            except ValueError:
                result.append(default)
        return result or [default]

    def _parse_enum(value: str, enum_cls, default):
        try:
            return enum_cls(value)
        except (ValueError, KeyError):
            return default

    auth_methods = _parse_enum_list(
        ext.get("auth_methods", []), AuthMethod, AuthMethod.UNKNOWN
    )
    api_types = _parse_enum_list(
        ext.get("api_types", []), APIType, APIType.UNKNOWN
    )

    record = AppRecord(
        id=app_id,
        app=app_name,
        category=category,
        one_line=ext.get("one_line", ""),
        auth_methods=auth_methods,
        access_model=_parse_enum(
            ext.get("access_model", "unknown"), AccessModel, AccessModel.UNKNOWN
        ),
        api_surface=APISurface(
            types=api_types,
            breadth=_parse_enum(
                ext.get("api_breadth", "unknown"), Breadth, Breadth.UNKNOWN
            ),
            webhooks=bool(ext.get("webhooks", False)),
            rate_limits_documented=bool(ext.get("rate_limits_documented", False)),
            notes=ext.get("api_notes", ""),
        ),
        existing_mcp=MCPInfo(
            exists=bool(ext.get("existing_mcp", False)),
            link=ext.get("mcp_link"),
            official=bool(ext.get("mcp_official", False)),
        ),
        developer_portal_url=ext.get("developer_portal_url"),
        buildable_today=ext.get("buildable_today"),
        blocker=_parse_enum(
            ext.get("blocker", "unknown"), Blocker, Blocker.UNKNOWN
        ),
        evidence_url=ext.get("evidence_url") or state.get("evidence_url", ""),
        secondary_evidence_urls=ext.get("secondary_urls", []),
        confidence=float(ext.get("confidence", 0.5)),
        verification_status=VerificationStatus.PENDING,
        fetch_tool=state.get("fetch_tool", "Unknown"),
        tool_source=state.get("tool_source", "Unknown"),
        failure_reason=state.get("failure_reason"),
        raw_llm_response=json.dumps(ext),
    )

    return {**state, "final_record": record.model_dump()}


# ─── Graph assembly ───────────────────────────────────────────────────────────

def build_research_graph() -> Any:
    """
    Build the research StateGraph.

    Topology (DAG — no cycles):
      START → plan_search → execute_search → fetch_docs → extract_info → build_record → END
    """
    graph = StateGraph(ResearchState)

    graph.add_node("plan_search",    plan_search_node)
    graph.add_node("execute_search", execute_search_node)
    graph.add_node("fetch_docs",     fetch_docs_node)
    graph.add_node("extract_info",   extract_info_node)
    graph.add_node("build_record",   build_record_node)

    # Linear edges — strictly forward, no back-edges
    graph.add_edge(START,             "plan_search")
    graph.add_edge("plan_search",     "execute_search")
    graph.add_edge("execute_search",  "fetch_docs")
    graph.add_edge("fetch_docs",      "extract_info")
    graph.add_edge("extract_info",    "build_record")
    graph.add_edge("build_record",    END)

    return graph.compile()


# ─── Public API ───────────────────────────────────────────────────────────────

_research_graph = None


def research_app(app_id: int, app_name: str, category: str, hint_url: str) -> AppRecord:
    """
    Research a single app and return a validated AppRecord.
    This is the primary entry point for the research pipeline.
    """
    global _research_graph
    if _research_graph is None:
        _research_graph = build_research_graph()

    initial_state: ResearchState = {
        "app_id": app_id,
        "app_name": app_name,
        "category": category,
        "hint_url": hint_url,
        "search_queries": [],
        "search_results": [],
        "page_text": "",
        "evidence_url": "",
        "fetch_tool": "Unknown",
        "tool_source": "Unknown",
        "failure_reason": "",
        "extraction": {},
        "final_record": {},
        "error": "",
    }

    final_state = _research_graph.invoke(
        initial_state,
        config={"recursion_limit": LANGGRAPH_RECURSION},
    )

    record_dict = final_state.get("final_record", {})
    if record_dict:
        return AppRecord(**record_dict)

    # Absolute fallback
    return AppRecord(
        id=app_id,
        app=app_name,
        category=category,
        one_line="Research graph returned no output",
        confidence=0.0,
        verification_status=VerificationStatus.NEEDS_HUMAN,
    )
