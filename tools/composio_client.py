"""
Composio client — initialises a Composio session and exposes search/fetch tools
formatted for LangChain/LangGraph agents.

Exact API used (Composio v0.17.x):
    from composio import Composio
    from composio_langchain import LangchainProvider

    composio = Composio(provider=LangchainProvider(), api_key=COMPOSIO_API_KEY)
    session  = composio.create(          # shortcut for composio.sessions.create()
        user_id=COMPOSIO_USER_ID,
        manage_connections={"wait_for_connections": True},
    )
    tools = session.tools()              # returns list[StructuredTool] for LangChain
"""

from __future__ import annotations

import logging
from typing import Optional

from config import (
    COMPOSIO_API_KEY,
    COMPOSIO_USER_ID,
    USE_COMPOSIO_SEARCH,
)

logger = logging.getLogger(__name__)

class ComposioToolError(Exception):
    """Exception raised when a Composio tool is unavailable or fails."""
    pass

# ─── Composio session (lazy singleton) ───────────────────────────────────────

_composio_session = None
_composio_tools: list = []


def _build_composio_session():
    """Build and return a Composio session with LangChain provider."""
    global _composio_session

    if _composio_session is not None:
        return _composio_session

    try:
        from composio import Composio
        from composio_langchain import LangchainProvider

        # LangchainProvider wraps tools as langchain StructuredTool objects
        composio = Composio(
            provider=LangchainProvider(),
            api_key=COMPOSIO_API_KEY,
        )

        # composio.create is a top-level shortcut for composio.sessions.create()
        session = composio.create(
            user_id=COMPOSIO_USER_ID,
            manage_connections={
                "wait_for_connections": True,
            },
        )

        _composio_session = session
        logger.info("✅ Composio session created (user_id=%s)", COMPOSIO_USER_ID)
        return session

    except Exception as exc:
        exc_str = str(exc)
        if "user_id does not match the user this playground API key is locked to" in exc_str or "10403" in exc_str:
            raise RuntimeError(
                "COMPOSIO_API_KEY is still a playground key — replace it in .env with a standard project API key."
            ) from exc
            
        logger.warning(
            "⚠️  Could not create Composio session: %s — falling back to native tools.",
            exc,
        )
        return None


def get_composio_tools() -> list:
    """
    Return LangChain-compatible tools from the Composio session.
    """
    global _composio_tools

    if not USE_COMPOSIO_SEARCH:
        logger.debug("Composio search disabled — COMPOSIO_API_KEY not set.")
        return []

    # Ensure session is successfully created (also acts as auth check)
    if _build_composio_session() is None:
        return []

    try:
        from composio import Composio
        from composio_langchain import LangchainProvider
        composio = Composio(provider=LangchainProvider(), api_key=COMPOSIO_API_KEY)
        tools = composio.tools.get(user_id=COMPOSIO_USER_ID, toolkits=['composio_search'])
        _composio_tools = list(tools) if tools else []
        logger.info("🔧 Loaded %d Composio tools from session (using composio_search)", len(_composio_tools))
        return _composio_tools

    except Exception as exc:
        logger.warning("⚠️  session.tools() failed: %s", exc)
        return []


def execute_composio_tool(tool_type: str, params: dict) -> str:
    """
    Execute a Composio tool natively by matching the tool_type ('search' or 'fetch').
    Raises ComposioToolError if not found or execution fails.
    """
    tools = get_composio_tools()
    if not tools:
        raise ComposioToolError("Composio is not configured or unavailable.")

    # Find the requested tool fuzzily
    target_tool = None
    for tool in tools:
        if tool_type == "search" and ("search" in tool.name.lower() or "tavily" in tool.name.lower()):
            target_tool = tool
            break
        elif tool_type == "fetch" and ("fetch" in tool.name.lower() or "scrape" in tool.name.lower() or "browser" in tool.name.lower() or "extract" in tool.name.lower()):
            target_tool = tool
            break

    if not target_tool:
        raise ComposioToolError(f"No active Composio tool found for type: {tool_type}")

    logger.info("🚀 Composio tool invoked: %s", target_tool.name)
    try:
        result = target_tool.invoke(params)
        return str(result)
    except Exception as exc:
        logger.error("Composio tool %s failed: %s", target_tool.name, exc)
        raise ComposioToolError(str(exc)) from exc


def get_search_tools_for_agent() -> list:
    """
    Convenience wrapper used by the research and verification agents.
    Returns Composio tools when available, empty list otherwise.
    The agent supplements with its own Tavily search tool regardless.
    """
    return get_composio_tools()
