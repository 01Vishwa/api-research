"""
Search tool — provider abstraction over Tavily and a lightweight Google fallback.
All public functions return a uniform list[dict] with keys: title, url, snippet.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from config import (
    TAVILY_API_KEY,
    USE_TAVILY_SEARCH,
    MAX_SEARCH_RESULTS,
    HTTP_TIMEOUT,
)

logger = logging.getLogger(__name__)


# ─── Result type ─────────────────────────────────────────────────────────────

def _make_result(title: str, url: str, snippet: str) -> dict:
    return {"title": title, "url": url, "snippet": snippet}


# ─── Tavily provider ─────────────────────────────────────────────────────────

async def _tavily_search(query: str, max_results: int) -> list[dict]:
    """Search via Tavily API (async wrapper around the sync client)."""
    try:
        from tavily import TavilyClient  # type: ignore
        client = TavilyClient(api_key=TAVILY_API_KEY)

        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(
            None,
            lambda: client.search(query, max_results=max_results, search_depth="basic"),
        )
        results = raw.get("results", [])
        return [
            _make_result(r.get("title", ""), r.get("url", ""), r.get("content", ""))
            for r in results
        ]
    except Exception as exc:
        logger.warning("Tavily search failed for '%s': %s", query, exc)
        return []


# ─── DuckDuckGo fallback (no API key needed) ──────────────────────────────────

async def _ddg_search(query: str, max_results: int) -> list[dict]:
    """
    Minimal DuckDuckGo Instant Answer API — no key required, limited but reliable.
    Used only as a last resort.
    """
    import httpx

    params = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1"}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get("https://api.duckduckgo.com/", params=params)
            data = resp.json()

        results: list[dict] = []
        for r in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(r, dict) and "FirstURL" in r:
                results.append(_make_result(
                    r.get("Text", "")[:100],
                    r.get("FirstURL", ""),
                    r.get("Text", ""),
                ))
        return results
    except Exception as exc:
        logger.warning("DDG search failed for '%s': %s", query, exc)
        return []


# ─── Public interface ─────────────────────────────────────────────────────────

async def web_search(
    query: str,
    max_results: int = MAX_SEARCH_RESULTS,
    provider: Optional[str] = None,
) -> tuple[list[dict], str, Optional[str]]:
    """
    Search the web and return uniform result dicts.

    Priority:
      1. Composio search tool (if available)
      2. Tavily (if TAVILY_API_KEY set)
      3. DuckDuckGo Instant Answer (fallback, no key)
    """
    # 1. Try Composio first as the primary execution layer
    try:
        from tools.composio_client import execute_composio_tool
        loop = asyncio.get_event_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(
                pool,
                lambda: execute_composio_tool("search", {"query": query})
            )
        
        # Try to parse Composio's output as JSON to extract URLs
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict) and "results" in parsed:
                return [_make_result(r.get("title", ""), r.get("url", ""), str(r.get("content", ""))) for r in parsed["results"]][:max_results], "composio", None
            elif isinstance(parsed, list):
                return [_make_result(r.get("title", ""), r.get("url", ""), str(r.get("content", ""))) for r in parsed][:max_results], "composio", None
        except json.JSONDecodeError:
            pass
        
        # If not JSON, return a dummy URL so it passes the deduplication filter
        dummy_url = f"composio://search/{query.replace(' ', '_')}"
        return [_make_result(f"Composio Search: {query}", dummy_url, result)], "composio", None

    except Exception as exc:
        err_str = str(exc).lower()
        if "tavily" in err_str and "account" in err_str:
            failure_reason = "composio_tavily_no_connected_account"
        else:
            failure_reason = "composio_search_failed"
        logger.warning("Composio search tool unavailable/failed. Falling back to Tavily API/DuckDuckGo. Reason: %s", exc)

    # 2. Fallback to Tavily
    if USE_TAVILY_SEARCH or (provider == "tavily"):
        results = await _tavily_search(query, max_results)
        if results:
            return results, "fallback_tavily", failure_reason

    # 3. Fallback to DuckDuckGo
    return await _ddg_search(query, max_results), "fallback_ddg", failure_reason


def web_search_sync(query: str, max_results: int = MAX_SEARCH_RESULTS) -> tuple[list[dict], str, Optional[str]]:
    """Sync convenience wrapper for use inside LangChain tool callables."""
    try:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run, web_search(query, max_results)
                    )
                    return future.result(timeout=30)
            return loop.run_until_complete(web_search(query, max_results))
        except RuntimeError:
            return asyncio.run(web_search(query, max_results))
    except Exception as exc:
        logger.error("web_search_sync failed: %s", exc)
        return [], "Unknown", str(exc)
